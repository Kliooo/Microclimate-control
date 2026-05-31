"""
Симуляция исполнительных устройств.

Устройства управляются автоматически (по отклонению от целевых параметров)
или вручную. Формируют device_state для физической модели.
"""
import numpy as np
from datetime import datetime


class DeviceSimulator:
    """Базовый класс устройства"""

    def __init__(self, name):
        self.name = name
        self.is_active = False
        self.intensity = 0.0
        self.manual_mode = False

    def set_manual_mode(self, enabled):
        self.manual_mode = enabled

    def manual_control(self, active, intensity=1.0):
        self.is_active = active
        self.intensity = np.clip(intensity, 0, 1) if active else 0.0

    def get_status(self):
        return {
            "name": self.name,
            "active": self.is_active,
            "intensity": self.intensity,
            "manual_mode": self.manual_mode,
        }


class AirConditioner(DeviceSimulator):
    """Кондиционер — охлаждение/обогрев"""

    def __init__(self):
        super().__init__("Кондиционер")
        self.mode = "cooling"  # "cooling" / "heating"


class Radiator(DeviceSimulator):
    """Радиатор — обогрев"""

    def __init__(self):
        super().__init__("Радиатор")


class Humidifier(DeviceSimulator):
    """Увлажнитель воздуха"""

    def __init__(self):
        super().__init__("Увлажнитель")


class Dehumidifier(DeviceSimulator):
    """Осушитель воздуха"""

    def __init__(self):
        super().__init__("Осушитель")


class Breather(DeviceSimulator):
    """Бризер (приточная вентиляция)"""

    def __init__(self):
        super().__init__("Бризер")


class AutoBlinds(DeviceSimulator):
    """Автоматические шторы"""

    def __init__(self):
        super().__init__("Шторы")


class DeviceController:
    """
    Контроллер всех устройств.

    Автоматический режим: устройства включаются/выключаются
    в зависимости от отклонения текущих параметров от целевых.

    Формирует device_state dict для передачи в физическую модель.
    """

    def __init__(self):
        self.ac = AirConditioner()
        self.radiator = Radiator()
        self.humidifier = Humidifier()
        self.dehumidifier = Dehumidifier()
        self.breather = Breather()
        self.blinds = AutoBlinds()

    def get_device_state(self):
        """
        Формирование device_state для физической модели.

        Returns:
            dict: состояние всех устройств в формате, понятном physics_model
        """
        return {
            "ac_active": self.ac.is_active,
            "ac_intensity": self.ac.intensity,
            "ac_mode": self.ac.mode,
            "radiator_active": self.radiator.is_active,
            "radiator_intensity": self.radiator.intensity,
            "humidifier_active": self.humidifier.is_active,
            "humidifier_intensity": self.humidifier.intensity,
            "dehumidifier_active": self.dehumidifier.is_active,
            "dehumidifier_intensity": self.dehumidifier.intensity,
            "breather_active": self.breather.is_active,
            "breather_intensity": self.breather.intensity,
            "blinds_active": self.blinds.is_active,
            "blinds_intensity": self.blinds.intensity,
        }

    def auto_control(self, current_state, target):
        """
        Автоматическое управление устройствами по отклонению от целевых значений.

        Args:
            current_state: dict с текущими параметрами (temperature, humidity, co2, illuminance)
            target: dict с целевыми параметрами
        """
        temp = current_state.get("temperature", 22)
        hum = current_state.get("humidity", 50)
        co2 = current_state.get("co2", 450)
        lux = current_state.get("illuminance", 300)

        target_temp = target.get("temperature", 22)
        target_hum = target.get("humidity", 50)
        target_co2_max = target.get("co2_max", 800)
        target_lux = target.get("illuminance", 300)

        # --- Температура ---
        temp_diff = temp - target_temp

        if not self.ac.manual_mode:
            if temp_diff > 0.5:
                # Теплее цели — включаем охлаждение
                self.ac.mode = "cooling"
                self.ac.is_active = True
                self.ac.intensity = np.clip(temp_diff / 2.0, 0.2, 1.0)
            elif temp_diff < -0.5:
                # Холоднее цели — включаем обогрев кондиционером
                self.ac.mode = "heating"
                self.ac.is_active = True
                self.ac.intensity = np.clip(abs(temp_diff) / 2.0, 0.2, 1.0)
            elif abs(temp_diff) < 0.2:
                self.ac.is_active = False
                self.ac.intensity = 0.0

        if not self.radiator.manual_mode:
            if temp_diff < -1.0:
                # Холодно — включаем радиатор
                self.radiator.is_active = True
                self.radiator.intensity = np.clip(abs(temp_diff) / 3.0, 0.3, 1.0)
            elif temp_diff > -0.3:
                self.radiator.is_active = False
                self.radiator.intensity = 0.0

        # --- CO2 ---
        if not self.breather.manual_mode:
            if co2 > target_co2_max:
                self.breather.is_active = True
                excess = co2 - target_co2_max
                self.breather.intensity = np.clip(excess / 150.0, 0.3, 1.0)
            elif co2 < target_co2_max * 0.8:
                self.breather.is_active = False
                self.breather.intensity = 0.0

        # --- Влажность ---
        hum_diff = hum - target_hum

        if not self.humidifier.manual_mode:
            if hum_diff < -3:
                # Сухо — включаем увлажнитель
                self.humidifier.is_active = True
                self.humidifier.intensity = np.clip(abs(hum_diff) / 8.0, 0.3, 1.0)
            elif hum_diff > -1:
                self.humidifier.is_active = False
                self.humidifier.intensity = 0.0

        if not self.dehumidifier.manual_mode:
            if hum_diff > 5:
                # Влажно — включаем осушитель
                self.dehumidifier.is_active = True
                self.dehumidifier.intensity = np.clip(hum_diff / 15.0, 0.3, 1.0)
            elif hum_diff < 2:
                self.dehumidifier.is_active = False
                self.dehumidifier.intensity = 0.0

        # --- Освещённость (шторы) ---
        if not self.blinds.manual_mode:
            if lux > target_lux + 150:
                self.blinds.is_active = True
                self.blinds.intensity = np.clip((lux - target_lux) / 400.0, 0.3, 0.9)
            elif lux < target_lux + 50:
                self.blinds.is_active = False
                self.blinds.intensity = 0.0

    def get_all_status(self):
        """Статус всех устройств для UI"""
        return {
            "ac": self.ac.get_status(),
            "radiator": self.radiator.get_status(),
            "humidifier": self.humidifier.get_status(),
            "dehumidifier": self.dehumidifier.get_status(),
            "breather": self.breather.get_status(),
            "blinds": self.blinds.get_status(),
        }

    # Для обратной совместимости с app.py
    def get_total_impact(self):
        """Deprecated: используйте get_device_state()"""
        return self.get_device_state()
