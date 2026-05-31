"""
Центральный хаб: нормализация данных, расчет PMV и IEQ
"""
import numpy as np
from src.constants import GOST_LIMITS, CHANGE_LIMITS, IEQ_WEIGHTS, INDEX_THRESHOLDS


class DataNormalizer:
    """Нормализация данных: фильтрация шумов и скользящее окно"""

    def __init__(self, window_minutes=10):
        self.window_minutes = window_minutes
        self.raw_buffer = []
        self.normalized_buffer = []

    def add_reading(self, reading):
        """Добавление нового измерения"""
        self.raw_buffer.append(reading)

    def get_normalized(self, current_values):
        """
        Получение нормализованных значений с использованием скользящего окна

        Args:
            current_values: Текущие показания датчиков

        Returns:
            dict: Нормализованные значения
        """
        self.raw_buffer.append(current_values)

        if len(self.raw_buffer) > self.window_minutes:
            self.raw_buffer = self.raw_buffer[-self.window_minutes:]

        normalized = {}

        for key in ["temperature", "humidity", "co2", "illuminance"]:
            values = [r[key] for r in self.raw_buffer if key in r]

            if len(values) > 0:
                if len(values) > 3:
                    mean = np.mean(values)
                    std = np.std(values)
                    if std > 0:
                        filtered = [v for v in values if abs(v - mean) <= 2 * std]
                        if filtered:
                            values = filtered

                normalized[key] = {
                    "mean": np.mean(values),
                    "std": np.std(values) if len(values) > 1 else 0,
                    "min": np.min(values),
                    "max": np.max(values),
                }

        self.normalized_buffer.append(normalized)
        return normalized

    def clear(self):
        """Очистка буферов"""
        self.raw_buffer = []
        self.normalized_buffer = []


class PMVCalculator:
    """Расчет индекса PMV (Predicted Mean Vote) по упрощенной модели Фангера"""

    def __init__(self):
        self.M = 1.0        # Метаболизм (met) - сидячая работа
        self.W = 0.0        # Механическая работа (W)
        self.I_cl = 0.9     # Теплопроводность одежды (clo)

    def calculate_pmv(self, temperature, humidity, air_speed=0.1,
                      radiant_temp=None, clothing=None):
        """
        Расчет PMV по упрощенной формуле

        Args:
            temperature: Температура воздуха (°C)
            humidity: Относительная влажность (%)
            air_speed: Скорость воздуха (м/с)
            radiant_temp: Радиационная температура (°C)
            clothing: Теплопроводность одежды (clo)

        Returns:
            float: Значение PMV (-3 до +3)
        """
        if radiant_temp is None:
            radiant_temp = temperature

        if clothing is not None:
            self.I_cl = clothing

        # Средняя температура
        t_a = temperature
        t_r = radiant_temp
        t = (t_a + t_r) / 2

        # Парциальное давление водяного пара (кПа)
        p_sat = 0.133 * np.exp((18.67 - t_a / (t_a + 243.5)) * np.log(610.6) - (18.67 - t_a / (t_a + 243.5)) * 243.5)
        p_a = humidity / 100 * p_sat / 1000

        # Теплопродукция
        M = self.M * 58.15  # Вт/м²

        # Механическая работа
        W = self.W * 58.15  # Вт/м²

        # Тепловое сопротивление одежды
        I_cl = self.I_cl * 0.155  # м²·К/Вт

        # Коэффициент теплоотдачи
        f_cl = 1.0 + 0.155 * self.I_cl * 3.96 * (1 + 0.4 * self.I_cl)

        # Температура поверхности одежды (итеративно)
        t_cl = t + 0.1  # Начальное приближение
        for _ in range(10):
            h_c = 2.38 * abs(t_cl - t_a) ** 0.25
            if air_speed > 0.1:
                h_c = max(h_c, 12.1 * np.sqrt(air_speed))
            t_cl = 35.7 - 0.028 * M - I_cl * (3.96 * f_cl * (t_cl ** 4 - t_r ** 4) + h_c * (t_cl - t_a))

        # Тепловой баланс
        L = M - W - 3.96 * f_cl * (t_cl ** 4 - t_r ** 4) * 0.0000000567 - h_c * (t_cl - t_a) - 0.42 * (M - W - 58.15) - 0.0014 * M * (44 - p_a * 1000) - 0.00001714 * M * (5867 - p_a * 1000)

        # PMV
        if abs(L) < 0.001:
            pmv = 0
        else:
            pmv_correction = 0.303 * np.exp(-0.036 * self.M) + 0.028
            pmv = pmv_correction * L

        pmv = np.clip(pmv, -3, 3)
        return round(pmv, 2)

    def calculate_pmv_simple(self, temperature, humidity):
        """Упрощенный расчет PMV на основе температуры и влажности"""
        ideal_temp = 22.0
        ideal_hum = 50.0

        temp_diff = temperature - ideal_temp
        hum_factor = (humidity - ideal_hum) / 50 * 0.3

        pmv = temp_diff * 0.35 + hum_factor
        pmv = np.clip(pmv, -3, 3)
        return round(pmv, 2)

    def calculate_ppd(self, pmv):
        """
        Расчет PPD (Predicted Percentage of Dissatisfied)

        Args:
            pmv: Значение PMV

        Returns:
            float: Процент недовольных (%)
        """
        ppd = 100 - 95 * np.exp(-0.03353 * pmv ** 4 - 0.2179 * pmv ** 2)
        return round(max(5, min(100, ppd)), 1)


class IEQCalculator:
    """Расчет общего индекса IEQ и суб-индексов"""

    def __init__(self, weights=None):
        self.weights = weights or IEQ_WEIGHTS

    def calculate_thermal_index(self, temperature, humidity, pmv=None):
        """
        Расчет термального суб-индекса

        Args:
            temperature: Температура (°C)
            humidity: Влажность (%)
            pmv: PMV (если уже рассчитан)

        Returns:
            float: Индекс 0-100
        """
        if pmv is None:
            pmv_calc = PMVCalculator()
            pmv = pmv_calc.calculate_pmv_simple(temperature, humidity)

        temp_diff = abs(temperature - 22)
        hum_diff = abs(humidity - 50)

        temp_score = max(0, 100 - temp_diff * 5)
        humidity_score = max(0, 100 - hum_diff * 1)
        pmv_score = max(0, 100 - abs(pmv) * 15)

        thermal_index = temp_score * 0.4 + humidity_score * 0.2 + pmv_score * 0.4
        return np.clip(thermal_index, 0, 100)

    def calculate_air_quality_index(self, co2):
        """Расчет индекса качества воздуха"""
        if co2 <= 500:
            return 100
        elif co2 <= 600:
            return 95
        elif co2 <= 700:
            return 85
        elif co2 <= 800:
            return 75
        elif co2 <= 1000:
            return 60
        else:
            return max(30, 60 - (co2 - 1000) * 0.05)

    def calculate_visual_index(self, illuminance):
        """Расчет визуального суб-индекса"""
        if illuminance >= 300:
            return 100
        elif illuminance >= 200:
            return 85
        elif illuminance >= 150:
            return 75
        elif illuminance >= 100:
            return 60
        else:
            return max(40, 60 - (150 - illuminance) * 0.2)

    def calculate_overall_ieq(self, thermal, air_quality, visual):
        """
        Расчет общего IEQ Score

        Args:
            thermal: Термальный индекс
            air_quality: Индекс качества воздуха
            visual: Визуальный индекс

        Returns:
            float: Общий IEQ Score 0-100
        """
        ieq = (thermal * self.weights["thermal"] +
               air_quality * self.weights["air_quality"] +
               visual * self.weights["visual"])
        return round(np.clip(ieq, 0, 100), 1)

    def get_ieq_report(self, temperature, humidity, co2, illuminance):
        """
        Полный расчет всех индексов

        Returns:
            dict: Отчет со всеми индексами
        """
        pmv_calc = PMVCalculator()
        pmv = pmv_calc.calculate_pmv_simple(temperature, humidity)
        ppd = pmv_calc.calculate_ppd(pmv)

        thermal = self.calculate_thermal_index(temperature, humidity, pmv)
        air_quality = self.calculate_air_quality_index(co2)
        visual = self.calculate_visual_index(illuminance)

        overall_ieq = self.calculate_overall_ieq(thermal, air_quality, visual)

        return {
            "pmv": pmv,
            "ppd": ppd,
            "thermal_index": round(thermal, 1),
            "air_quality_index": round(air_quality, 1),
            "visual_index": round(visual, 1),
            "overall_ieq": overall_ieq,
            "comfort_class": self._get_comfort_class(pmv),
        }

    def _get_comfort_class(self, pmv):
        """Определение класса комфорта по PMV"""
        abs_pmv = abs(pmv)
        if abs_pmv <= 0.2:
            return "A"
        elif abs_pmv <= 0.5:
            return "B"
        elif abs_pmv <= 1.0:
            return "C"
        else:
            return "D"


class SafetyChecker:
    """Проверка безопасности по ГОСТ и ограничениям"""

    def __init__(self):
        self.limits = GOST_LIMITS
        self.change_limits = CHANGE_LIMITS

    def check_value_limits(self, temperature, humidity, season="summer"):
        """
        Проверка значений на соответствие ГОСТ

        Returns:
            dict: Результат проверки
        """
        results = {
            "valid": True,
            "violations": [],
            "warnings": [],
        }

        if season == "winter":
            temp_limits = self.limits["temperature_winter"]
        else:
            temp_limits = self.limits["temperature_summer"]

        if temperature < temp_limits["min"]:
            results["violations"].append(f"Температура ниже нормы: {temperature}C < {temp_limits['min']}C")
        elif temperature > temp_limits["max"]:
            results["violations"].append(f"Температура выше нормы: {temperature}C > {temp_limits['max']}C")

        if humidity < self.limits["humidity"]["min"]:
            results["warnings"].append(f"Влажность низкая: {humidity}% < {self.limits['humidity']['min']}%")
        elif humidity > self.limits["humidity"]["max"]:
            results["warnings"].append(f"Влажность высокая: {humidity}% > {self.limits['humidity']['max']}%")

        results["valid"] = len(results["violations"]) == 0
        return results

    def check_change_limits(self, old_value, new_value, param_type):
        """
        Проверка допустимости изменения

        Args:
            old_value: Предыдущее значение
            new_value: Новое значение
            param_type: Тип параметра

        Returns:
            tuple: (допустимо, скорректированное_значение)
        """
        max_change = self.change_limits.get(param_type, float('inf'))
        difference = new_value - old_value

        if abs(difference) <= max_change:
            return True, new_value

        corrected = old_value + np.sign(difference) * max_change
        return False, corrected


if __name__ == "__main__":
    print("Тест расчета PMV:")
    pmv_calc = PMVCalculator()

    for temp in [18, 20, 22, 24, 26, 28]:
        pmv = pmv_calc.calculate_pmv_simple(temp, 50)
        print(f"  t={temp}C: PMV={pmv}")

    print("\nТест расчета IEQ:")
    ieq_calc = IEQCalculator()
    report = ieq_calc.get_ieq_report(
        temperature=23,
        humidity=50,
        co2=600,
        illuminance=300,
    )
    for key, value in report.items():
        print(f"  {key}: {value}")
