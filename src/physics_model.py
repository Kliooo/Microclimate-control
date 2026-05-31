"""
Физическая модель помещения для симуляции микроклимата.

Реализует причинно-следственную модель, где параметры среды
определяются балансом энергии, массы CO2 и влаги.

Без работающих устройств:
- Температура дрейфует к уличной (через теплопотери)
- CO2 растёт от людей (без вентиляции)
- Влажность меняется от людей и инфильтрации

Устройства — единственное, что удерживает параметры в норме.
"""
import numpy as np
import yaml
import os


def load_config(path="configs/room_config.yaml"):
    """Загрузка конфигурации из YAML"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Конфиг не найден: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class RoomPhysicsModel:
    """
    Физическая модель помещения.

    Каждый вызов step() продвигает симуляцию на 1 минуту.
    Все расчёты основаны на тепловом балансе и балансе масс.
    """

    # Физические константы
    AIR_DENSITY = 1.2          # кг/м³
    AIR_SPECIFIC_HEAT = 1005   # Дж/(кг·К)
    WATER_VAPOR_HEAT = 2450    # кДж/кг (теплота испарения)
    OUTDOOR_CO2 = 420.0        # Фоновый уровень CO2 на улице (ppm)
    STEFAN_BOLTZMANN = 5.67e-8 # Вт/(м²·К⁴)

    def __init__(self, config=None, config_path="configs/room_config.yaml"):
        """
        Args:
            config: dict с конфигурацией (если None — загружается из файла)
            config_path: путь к YAML-файлу конфигурации
        """
        if config is None:
            config = load_config(config_path)
        self.cfg = config

        # Вычисляемые параметры
        self.volume = (self.cfg["geometry"]["floor_area_m2"] *
                       self.cfg["geometry"]["ceiling_height_m"])
        self.air_mass = self.volume * self.AIR_DENSITY  # кг воздуха

        # Текущее состояние
        self._init_state()

        # Кеш сезонных параметров
        self._update_season_params()

    def _init_state(self):
        """Инициализация начального состояния"""
        init = self.cfg["initial_conditions"]

        if init["mode"] == "comfort":
            self.temperature = init["temperature_c"]
            self.humidity = init["humidity_pct"]
            self.co2 = init["co2_ppm"]
        else:
            # Равновесие с улицей (холодное помещение)
            season = self.cfg["climate"]["season"]
            season_cfg = self.cfg["climate"][season]
            self.temperature = (season_cfg["temp_min_c"] + season_cfg["temp_max_c"]) / 2
            self.humidity = season_cfg["humidity_mean"]
            self.co2 = self.OUTDOOR_CO2

        # Радиационная температура (начально = температуре воздуха)
        self.radiant_temperature = self.temperature

        # Температура внутренних поверхностей стен (тепловая инерция)
        self.wall_surface_temp = self.temperature

        # Освещённость
        self.illuminance = 0.0

        # Счётчик шагов
        self.step_count = 0

    def _update_season_params(self):
        """Обновление кешированных сезонных параметров"""
        season = self.cfg["climate"]["season"]
        self.season_cfg = self.cfg["climate"][season]

    def get_outdoor_temperature(self, hour, minute=0):
        """
        Расчёт уличной температуры по времени суток.
        Суточный ход: минимум в 5-6 утра, максимум в 14-15 часов.

        Args:
            hour: час (0-23)
            minute: минута (0-59)

        Returns:
            float: температура на улице (°C)
        """
        t_min = self.season_cfg["temp_min_c"]
        t_max = self.season_cfg["temp_max_c"]
        t_mean = (t_min + t_max) / 2
        t_amplitude = (t_max - t_min) / 2

        # Синусоидальный ход: минимум в 5:00, максимум в 15:00
        time_hours = hour + minute / 60.0
        phase = (time_hours - 5.0) / 24.0 * 2 * np.pi
        temp = t_mean + t_amplitude * np.sin(phase - np.pi / 2)

        return temp

    def get_outdoor_humidity(self, outdoor_temp):
        """
        Расчёт уличной влажности.
        Обратная корреляция с температурой в пределах суток.
        """
        base = self.season_cfg["humidity_mean"]
        t_mean = (self.season_cfg["temp_min_c"] + self.season_cfg["temp_max_c"]) / 2
        # При повышении температуры относительная влажность падает
        deviation = -(outdoor_temp - t_mean) * 2.0
        return np.clip(base + deviation, 30, 98)

    def get_solar_radiation(self, hour, minute=0):
        """
        Расчёт солнечной радиации на вертикальную поверхность окна (Вт/м²).

        Учитывает:
        - Время суток (синусоидальный профиль)
        - Облачность
        - Ориентацию окна

        Returns:
            float: солнечная радиация (Вт/м²)
        """
        solar_max = self.season_cfg["solar_max_w_m2"]
        cloud_cover = self.season_cfg["cloud_cover_mean"]

        # Определяем световой день (упрощённо по сезону)
        season = self.cfg["climate"]["season"]
        if season == "winter":
            sunrise, sunset = 9, 16
        elif season == "summer":
            sunrise, sunset = 5, 21
        elif season == "spring":
            sunrise, sunset = 6, 19
        else:  # autumn
            sunrise, sunset = 7, 17

        time_h = hour + minute / 60.0

        if time_h < sunrise or time_h > sunset:
            return 0.0

        # Синусоидальный профиль
        day_length = sunset - sunrise
        progress = (time_h - sunrise) / day_length
        base_radiation = solar_max * np.sin(progress * np.pi)

        # Облачность снижает радиацию
        cloud_factor = 1.0 - 0.75 * cloud_cover

        # Ориентация окна
        orientation = self.cfg["envelope"]["window_orientation"]
        if orientation == "south":
            orient_factor = 1.0
        elif orientation == "north":
            orient_factor = 0.25
        elif orientation == "east":
            # Утром больше, вечером меньше
            orient_factor = max(0, 1.0 - abs(time_h - 9) / 6)
        elif orientation == "west":
            # Вечером больше, утром меньше
            orient_factor = max(0, 1.0 - abs(time_h - 16) / 6)
        else:
            orient_factor = 0.5

        return max(0, base_radiation * cloud_factor * orient_factor)

    def get_occupants(self, hour):
        """Количество людей в помещении по профилю"""
        profile = self.cfg["internal_gains"]["occupancy_profile"]
        return profile.get(hour, profile.get(str(hour), 0))

    def step(self, hour, minute=0, device_state=None):
        """
        Один шаг симуляции (1 минута).

        Args:
            hour: текущий час (0-23)
            minute: текущая минута (0-59)
            device_state: dict с состоянием устройств
                {
                    "ac_active": bool, "ac_intensity": float, "ac_mode": "cooling"/"heating",
                    "radiator_active": bool, "radiator_intensity": float,
                    "humidifier_active": bool, "humidifier_intensity": float,
                    "dehumidifier_active": bool, "dehumidifier_intensity": float,
                    "breather_active": bool, "breather_intensity": float,
                    "blinds_active": bool, "blinds_intensity": float,
                }

        Returns:
            dict: текущие показания всех параметров
        """
        if device_state is None:
            device_state = {}

        dt = 60.0  # шаг = 60 секунд

        # --- Внешние условия ---
        outdoor_temp = self.get_outdoor_temperature(hour, minute)
        outdoor_humidity = self.get_outdoor_humidity(outdoor_temp)
        solar_radiation = self.get_solar_radiation(hour, minute)
        occupants = self.get_occupants(hour)

        # --- ТЕМПЕРАТУРА: тепловой баланс ---
        prev_temperature = self.temperature
        self.temperature = self._calc_temperature(
            dt, outdoor_temp, solar_radiation, occupants, device_state
        )

        # --- CO2: баланс масс ---
        self.co2 = self._calc_co2(
            dt, occupants, device_state
        )

        # --- ВЛАЖНОСТЬ: баланс влаги ---
        self.humidity = self._calc_humidity(
            dt, outdoor_temp, outdoor_humidity, occupants, device_state, prev_temperature
        )

        # --- ОСВЕЩЁННОСТЬ ---
        self.illuminance = self._calc_illuminance(
            hour, minute, solar_radiation, occupants, device_state
        )

        # --- Радиационная температура ---
        # Медленно следует за температурой воздуха и стен
        self.radiant_temperature += 0.05 * (self.temperature - self.radiant_temperature)

        self.step_count += 1

        return {
            "temperature": self.temperature,
            "humidity": self.humidity,
            "co2": self.co2,
            "illuminance": self.illuminance,
            "radiant_temperature": self.radiant_temperature,
            "outdoor_temperature": outdoor_temp,
            "outdoor_humidity": outdoor_humidity,
            "solar_radiation": solar_radiation,
            "occupants": occupants,
        }

    def _calc_temperature(self, dt, outdoor_temp, solar_rad, occupants, devices):
        """
        Расчёт температуры через тепловой баланс.

        Q_total = Q_walls + Q_windows + Q_floor + Q_ceiling
                + Q_infiltration + Q_ventilation
                + Q_solar + Q_people + Q_equipment
                + Q_devices

        dT = Q_total * dt / C_effective
        """
        env = self.cfg["envelope"]
        gains = self.cfg["internal_gains"]
        thermal_mass = self.cfg["thermal_mass"]["effective_capacity_kj_per_k"] * 1000  # Дж/К

        T = self.temperature
        T_out = outdoor_temp

        # === ТЕПЛОПОТЕРИ (отрицательные при T > T_out) ===

        # Через стены: Q = U * A * (T_out - T)
        q_walls = env["wall_u_value"] * env["wall_area_m2"] * (T_out - T)

        # Через окна: Q = U * A * (T_out - T)
        q_windows_cond = env["window_u_value"] * env["window_area_m2"] * (T_out - T)

        # Через пол: Q = U * A * (T_ground - T)
        t_ground = env["ground_temperature_c"]
        q_floor = env["floor_u_value"] * self.cfg["geometry"]["floor_area_m2"] * (t_ground - T)

        # Через потолок: Q = U * A * (T_adjacent - T)
        t_ceiling = env["ceiling_adjacent_temp_c"]
        q_ceiling = env["ceiling_u_value"] * self.cfg["geometry"]["floor_area_m2"] * (t_ceiling - T)

        # Инфильтрация (неконтролируемый воздухообмен)
        infiltration_flow = (self.cfg["ventilation"]["infiltration_ach"] *
                             self.volume / 3600.0)  # м³/с
        q_infiltration = (infiltration_flow * self.AIR_DENSITY *
                          self.AIR_SPECIFIC_HEAT * (T_out - T))

        # === ТЕПЛОПОСТУПЛЕНИЯ ===

        # Солнечная радиация через окна
        blinds_active = devices.get("blinds_active", False)
        blinds_intensity = devices.get("blinds_intensity", 0.0)
        solar_block = 0.0
        if blinds_active:
            solar_block = self.cfg["devices"]["blinds"]["solar_block_factor"] * blinds_intensity

        g_factor = env["window_g_factor"]
        q_solar = solar_rad * env["window_area_m2"] * g_factor * (1 - solar_block)

        # Тепло от людей
        q_people = occupants * gains["heat_per_person_w"]

        # Тепло от оборудования (только когда есть люди)
        q_equipment = gains["equipment_heat_w"] if occupants > 0 else 0.0

        # === УСТРОЙСТВА ===

        # Кондиционер
        q_ac = 0.0
        if devices.get("ac_active", False):
            intensity = devices.get("ac_intensity", 0.5)
            mode = devices.get("ac_mode", "cooling")
            if mode == "cooling":
                q_ac = -self.cfg["devices"]["air_conditioner"]["cooling_power_w"] * intensity
            else:
                q_ac = self.cfg["devices"]["air_conditioner"]["heating_power_w"] * intensity

        # Радиатор
        q_radiator = 0.0
        if devices.get("radiator_active", False):
            intensity = devices.get("radiator_intensity", 0.5)
            q_radiator = self.cfg["devices"]["radiator"]["heating_power_w"] * intensity

        # Бризер (приточная вентиляция) — вносит/выносит тепло
        q_ventilation = 0.0
        if devices.get("breather_active", False):
            intensity = devices.get("breather_intensity", 0.5)
            max_flow = self.cfg["devices"]["breather"]["max_flow_m3h"]
            flow_m3s = max_flow * intensity / 3600.0

            if self.cfg["devices"]["breather"]["has_heater"]:
                # С подогревом: приточный воздух нагревается до ~18°C
                supply_temp = max(T_out, min(18.0, T_out + 20.0))
                heater_power = self.cfg["devices"]["breather"]["heater_power_w"]
                # Ограничиваем подогрев мощностью нагревателя
                max_heating = heater_power  # Вт
                needed_heating = (flow_m3s * self.AIR_DENSITY *
                                  self.AIR_SPECIFIC_HEAT * (supply_temp - T_out))
                if needed_heating > max_heating:
                    supply_temp = T_out + max_heating / (flow_m3s * self.AIR_DENSITY *
                                                         self.AIR_SPECIFIC_HEAT + 1e-9)
            else:
                supply_temp = T_out

            q_ventilation = (flow_m3s * self.AIR_DENSITY *
                             self.AIR_SPECIFIC_HEAT * (supply_temp - T))

        # === СУММАРНЫЙ БАЛАНС ===
        q_total = (q_walls + q_windows_cond + q_floor + q_ceiling +
                   q_infiltration + q_ventilation +
                   q_solar + q_people + q_equipment +
                   q_ac + q_radiator)

        # dT = Q * dt / C
        dT = q_total * dt / thermal_mass

        new_temp = T + dT

        # Физические ограничения (не может быть ниже уличной - 5 или выше 45)
        new_temp = np.clip(new_temp, min(T_out - 5, 5), 45)

        return new_temp

    def _calc_co2(self, dt, occupants, devices):
        """
        Расчёт CO2 через баланс масс.

        dC/dt = (G_people - Q_vent * (C - C_out) - Q_infil * (C - C_out)) / V
        """
        C = self.co2
        C_out = self.OUTDOOR_CO2
        V = self.volume
        gains = self.cfg["internal_gains"]

        # Генерация CO2 людьми (л/с -> ppm/с)
        # 1 л CO2 в V м³ воздуха = 1e6 / (V * 1000) ppm = 1000/V ppm
        co2_generation_ls = occupants * gains["co2_per_person_lps"]
        co2_generation_ppm_s = co2_generation_ls * (1e6 / (V * 1000))

        # Удаление через инфильтрацию
        infil_flow = self.cfg["ventilation"]["infiltration_ach"] * V / 3600.0  # м³/с
        co2_removal_infil = infil_flow / V * (C - C_out)  # ppm/с

        # Удаление через бризер
        co2_removal_vent = 0.0
        if devices.get("breather_active", False):
            intensity = devices.get("breather_intensity", 0.5)
            max_flow = self.cfg["devices"]["breather"]["max_flow_m3h"]
            flow_m3s = max_flow * intensity / 3600.0
            co2_removal_vent = flow_m3s / V * (C - C_out)  # ppm/с

        # Баланс
        dC = (co2_generation_ppm_s - co2_removal_infil - co2_removal_vent) * dt

        new_co2 = C + dC
        return np.clip(new_co2, self.OUTDOOR_CO2, 5000)

    def _calc_humidity(self, dt, outdoor_temp, outdoor_humidity, occupants, devices, prev_temperature=None):
        """
        Расчёт относительной влажности через баланс влаги.

        Работаем с абсолютной влажностью (г/м³), потом пересчитываем в RH.
        """
        if prev_temperature is None:
            prev_temperature = self.temperature
        RH = self.humidity
        V = self.volume
        gains = self.cfg["internal_gains"]

        # Текущая абсолютная влажность внутри (г/м³)
        # Используем prev_temperature: RH был измерен ДО обновления температуры
        abs_hum_inside = self._rh_to_absolute(RH, prev_temperature)

        # Абсолютная влажность на улице
        abs_hum_outside = self._rh_to_absolute(outdoor_humidity, outdoor_temp)

        # Генерация влаги людьми (г/ч -> г/с)
        moisture_gen = occupants * gains["moisture_per_person_gh"] / 3600.0  # г/с

        # Изменение абсолютной влажности от генерации (г/м³/с)
        d_abs_gen = moisture_gen / V

        # Обмен через инфильтрацию
        infil_flow = self.cfg["ventilation"]["infiltration_ach"] * V / 3600.0  # м³/с
        d_abs_infil = infil_flow / V * (abs_hum_outside - abs_hum_inside)

        # Обмен через бризер
        d_abs_vent = 0.0
        if devices.get("breather_active", False):
            intensity = devices.get("breather_intensity", 0.5)
            max_flow = self.cfg["devices"]["breather"]["max_flow_m3h"]
            flow_m3s = max_flow * intensity / 3600.0
            d_abs_vent = flow_m3s / V * (abs_hum_outside - abs_hum_inside)

        # Увлажнитель
        d_abs_humidifier = 0.0
        if devices.get("humidifier_active", False):
            intensity = devices.get("humidifier_intensity", 0.5)
            capacity_ml_h = self.cfg["devices"]["humidifier"]["capacity_ml_h"]
            # мл/ч = г/ч (плотность воды ~1)
            moisture_added = capacity_ml_h * intensity / 3600.0  # г/с
            d_abs_humidifier = moisture_added / V

        # Осушитель
        d_abs_dehumidifier = 0.0
        if devices.get("dehumidifier_active", False):
            intensity = devices.get("dehumidifier_intensity", 0.5)
            capacity_ml_h = self.cfg["devices"]["dehumidifier"]["capacity_ml_h"]
            moisture_removed = capacity_ml_h * intensity / 3600.0  # г/с
            d_abs_dehumidifier = -moisture_removed / V

        # Суммарное изменение абсолютной влажности
        d_abs_total = (d_abs_gen + d_abs_infil + d_abs_vent +
                       d_abs_humidifier + d_abs_dehumidifier)

        new_abs_hum = abs_hum_inside + d_abs_total * dt
        new_abs_hum = max(0.5, new_abs_hum)  # Не может быть отрицательной

        # Пересчёт в относительную влажность при текущей температуре
        new_rh = self._absolute_to_rh(new_abs_hum, self.temperature)
        return np.clip(new_rh, 5, 99)

    def _calc_illuminance(self, hour, minute, solar_rad, occupants, devices):
        """Расчёт освещённости"""
        lighting = self.cfg["lighting"]

        # Естественный свет (пропорционален солнечной радиации)
        # Грубая оценка: 100 Вт/м² солнца ~ 10000 люкс на улице ~ 500 люкс внутри
        season = self.cfg["climate"]["season"]
        if season == "summer":
            max_lux = lighting["max_natural_lux_summer"]
        else:
            max_lux = lighting["max_natural_lux_winter"]

        solar_max = self.season_cfg["solar_max_w_m2"]
        if solar_max > 0:
            natural_lux = max_lux * (solar_rad / solar_max)
        else:
            natural_lux = 0

        # Шторы блокируют свет
        if devices.get("blinds_active", False):
            intensity = devices.get("blinds_intensity", 0.5)
            block = self.cfg["devices"]["blinds"]["light_block_factor"] * intensity
            natural_lux *= (1 - block)

        # Искусственное освещение
        artificial_lux = 0.0
        if lighting["artificial_on_with_people"] and occupants > 0:
            artificial_lux = lighting["artificial_lux"]

        total = natural_lux + artificial_lux
        return max(0, total)

    # --- Вспомогательные функции для влажности ---

    @staticmethod
    def _saturation_pressure(temp_c):
        """
        Давление насыщенного водяного пара (Па) по формуле Магнуса.
        """
        return 610.94 * np.exp(17.625 * temp_c / (temp_c + 243.04))

    @classmethod
    def _rh_to_absolute(cls, rh_pct, temp_c):
        """
        Перевод относительной влажности в абсолютную (г/м³).

        abs_humidity = (RH/100) * p_sat / (R_v * T_kelvin) * 1000
        R_v = 461.5 Дж/(кг·К)
        """
        p_sat = cls._saturation_pressure(temp_c)
        T_kelvin = temp_c + 273.15
        # кг/м³ -> г/м³ (*1000)
        return (rh_pct / 100.0) * p_sat / (461.5 * T_kelvin) * 1000.0

    @classmethod
    def _absolute_to_rh(cls, abs_hum_g_m3, temp_c):
        """
        Перевод абсолютной влажности (г/м³) в относительную (%).
        """
        p_sat = cls._saturation_pressure(temp_c)
        T_kelvin = temp_c + 273.15
        max_abs = p_sat / (461.5 * T_kelvin) * 1000.0
        if max_abs < 1e-9:
            return 50.0
        return (abs_hum_g_m3 / max_abs) * 100.0

    def reset(self):
        """Сброс модели к начальным условиям"""
        self._init_state()
        self.step_count = 0

    def set_season(self, season):
        """Смена сезона"""
        if season in ("winter", "spring", "summer", "autumn"):
            self.cfg["climate"]["season"] = season
            self._update_season_params()
