"""
Генератор данных датчиков и внешней среды.

Обёртка над физической моделью (physics_model.py).
Добавляет шум датчиков и редкие выбросы поверх "истинных" значений.
"""
import numpy as np
from datetime import datetime
import yaml
import os

from src.physics_model import RoomPhysicsModel, load_config


class SensorDataGenerator:
    """
    Генератор показаний датчиков.

    Внутри использует RoomPhysicsModel для расчёта реальных параметров,
    затем добавляет шум измерений и редкие аномалии.
    """

    def __init__(self, seed=None, config_path="configs/room_config.yaml"):
        """
        Args:
            seed: seed для воспроизводимости шума
            config_path: путь к YAML-конфигу
        """
        if seed is not None:
            np.random.seed(seed)

        self.config_path = config_path
        self.cfg = load_config(config_path)
        self.physics = RoomPhysicsModel(config=self.cfg)

        # Параметры шума из конфига
        self.noise_cfg = self.cfg.get("sensors", {})
        self.step_count = 0

    def generate_readings(self, hour=None, minute=0, device_state=None):
        """
        Генерация показаний датчиков на текущем шаге.

        Args:
            hour: час суток (0-23). Если None — берётся текущий.
            minute: минута (0-59)
            device_state: dict с состоянием устройств (из DeviceController)

        Returns:
            dict: показания датчиков с шумом + метаданные
        """
        if hour is None:
            now = datetime.now()
            hour = now.hour
            minute = now.minute

        self.step_count += 1

        # Физическая модель рассчитывает истинные значения
        true_values = self.physics.step(hour, minute, device_state)

        # Добавляем шум датчиков
        readings = self._apply_sensor_noise(true_values)

        # Добавляем редкие выбросы
        readings = self._apply_outliers(readings)

        # Метаданные
        readings["timestamp"] = datetime.now()
        readings["outdoor_temperature"] = true_values["outdoor_temperature"]
        readings["outdoor_humidity"] = true_values["outdoor_humidity"]
        readings["solar_radiation"] = true_values["solar_radiation"]
        readings["occupants"] = true_values["occupants"]

        return readings

    def _apply_sensor_noise(self, true_values):
        """Добавление гауссовского шума измерений"""
        noise_std = {
            "temperature": self.noise_cfg.get("temperature_noise_std", 0.05),
            "humidity": self.noise_cfg.get("humidity_noise_std", 0.3),
            "co2": self.noise_cfg.get("co2_noise_std", 8.0),
            "illuminance": self.noise_cfg.get("illuminance_noise_std", 5.0),
        }

        readings = {}
        for param in ["temperature", "humidity", "co2", "illuminance"]:
            true_val = true_values.get(param, 0)
            std = noise_std.get(param, 0)
            readings[param] = true_val + np.random.normal(0, std)

        # Ограничения физических диапазонов
        readings["temperature"] = np.clip(readings["temperature"], -10, 50)
        readings["humidity"] = np.clip(readings["humidity"], 5, 99)
        readings["co2"] = np.clip(readings["co2"], 350, 5000)
        readings["illuminance"] = max(0, readings["illuminance"])

        return readings

    def _apply_outliers(self, readings):
        """Добавление редких выбросов (аномалий датчиков)"""
        prob = self.noise_cfg.get("outlier_probability", 0.002)
        mag = self.noise_cfg.get("outlier_magnitude", 0.12)

        for param in ["temperature", "humidity", "co2", "illuminance"]:
            if param in readings and np.random.random() < prob:
                direction = np.random.choice([-1, 1])
                readings[param] *= (1 + direction * mag)

        return readings

    def get_state(self):
        """Получение текущего истинного состояния (без шума)"""
        return {
            "temperature": self.physics.temperature,
            "humidity": self.physics.humidity,
            "co2": self.physics.co2,
            "illuminance": self.physics.illuminance,
            "radiant_temperature": self.physics.radiant_temperature,
        }

    def set_season(self, season):
        """Смена сезона"""
        self.physics.set_season(season)

    def reset(self):
        """Сброс к начальным условиям"""
        self.physics.reset()
        self.step_count = 0


class ExternalEnvironmentSimulator:
    """
    Симулятор внешней среды.

    В новой архитектуре внешние условия рассчитываются внутри
    RoomPhysicsModel, но этот класс остаётся для:
    1. Совместимости с app.py (геолокация)
    2. Предоставления данных о погоде для UI
    """

    def __init__(self, seed=None, config_path="configs/room_config.yaml"):
        if seed is not None:
            np.random.seed(seed)

        self.cfg = load_config(config_path)
        season = self.cfg["climate"]["season"]
        self.season_cfg = self.cfg["climate"][season]

        # Геолокация
        self.current_distance = 25.0
        self.distance_direction = -1
        self.step_count = 0

    def get_weather_data(self, hour=None):
        """
        Данные о погоде для отображения в UI.
        Реальный расчёт температуры делается в physics_model,
        здесь — для отображения на графиках.
        """
        if hour is None:
            hour = datetime.now().hour

        self.step_count += 1

        # Суточный ход температуры
        t_min = self.season_cfg["temp_min_c"]
        t_max = self.season_cfg["temp_max_c"]
        t_mean = (t_min + t_max) / 2
        t_amplitude = (t_max - t_min) / 2

        time_h = hour
        phase = (time_h - 5.0) / 24.0 * 2 * np.pi
        outdoor_temp = t_mean + t_amplitude * np.sin(phase - np.pi / 2)
        outdoor_temp += np.random.normal(0, 0.15)

        # Влажность
        outdoor_humidity = self.season_cfg["humidity_mean"]
        outdoor_humidity += -(outdoor_temp - t_mean) * 2.0
        outdoor_humidity = np.clip(outdoor_humidity + np.random.normal(0, 0.5), 30, 98)

        return {
            "outdoor_temperature": round(outdoor_temp, 1),
            "outdoor_humidity": round(outdoor_humidity, 1),
            "weather_description": self._get_weather_description(outdoor_temp),
            "timestamp": datetime.now(),
        }

    def _get_weather_description(self, temp):
        if temp < -10:
            return "Мороз"
        elif temp < 0:
            return "Снег"
        elif temp < 10:
            return "Холодно"
        elif temp < 18:
            return "Прохладно"
        elif temp < 25:
            return "Тепло"
        else:
            return "Жарко"

    def get_geolocation(self):
        """Симуляция геолокации пользователя"""
        if self.step_count % 50 == 0:
            if self.current_distance < 2:
                self.distance_direction = 1
            elif self.current_distance > 45:
                self.distance_direction = -1
            else:
                self.distance_direction = np.random.choice([-1, 1])

        speed = np.random.uniform(0.1, 0.5)
        self.current_distance += self.distance_direction * speed
        self.current_distance = np.clip(self.current_distance, 0, 50)

        distance = max(0, self.current_distance + np.random.normal(0, 0.1))
        eta_minutes = distance * 2

        return {
            "distance_km": round(distance, 1),
            "eta_minutes": int(eta_minutes),
            "user_approaching": self.distance_direction < 0 and distance < 10,
            "timestamp": datetime.now(),
        }


