"""
Модуль для получения реальных данных о погоде через Open-Meteo API
"""
import requests
from datetime import datetime
import time


class RealWeatherAPI:
    """
    Класс для работы с Open-Meteo API
    """

    def __init__(self, lat=59.9311, lon=30.3609):
        """
        Инициализация API клиента

        Args:
            lat: Широта (по умолчанию Санкт-Петербург)
            lon: Долгота (по умолчанию Санкт-Петербург)
        """
        self.lat = lat
        self.lon = lon
        self.base_url = "https://api.open-meteo.com/v1/forecast"
        self.last_request_time = 0
        self.min_request_interval = 600  # 10 минут между запросами
        self.cached_data = None

    def set_location(self, lat, lon):
        """Установка новых координат"""
        self.lat = lat
        self.lon = lon
        self.cached_data = None  # Сброс кеша при смене локации

    def get_weather_data(self):
        """
        Получение данных о погоде

        Returns:
            dict: Данные о погоде в формате, совместимом с симулятором
        """
        current_time = time.time()

        # Проверка кеша (не делаем запрос чаще раза в 10 минут)
        if self.cached_data and (current_time - self.last_request_time) < self.min_request_interval:
            return self.cached_data

        try:
            params = {
                "latitude": self.lat,
                "longitude": self.lon,
                "current": "temperature_2m,relative_humidity_2m,pressure_msl,wind_speed_10m,cloud_cover",
                "timezone": "auto"
            }

            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            current = data["current"]

            # Преобразование в формат симулятора
            weather_data = {
                "outdoor_temperature": round(current["temperature_2m"], 1),
                "outdoor_humidity": round(current["relative_humidity_2m"], 1),
                "weather_description": self._get_weather_description(current["cloud_cover"]),
                "timestamp": datetime.now(),
                "pressure": round(current["pressure_msl"]),
                "wind_speed": round(current["wind_speed_10m"], 1),
                "clouds": round(current["cloud_cover"]),
            }

            self.cached_data = weather_data
            self.last_request_time = current_time

            return weather_data

        except requests.exceptions.RequestException as e:
            print(f"Ошибка при запросе к Open-Meteo API: {e}")

            # Возврат кешированных данных или значений по умолчанию
            if self.cached_data:
                return self.cached_data
            else:
                return {
                    "outdoor_temperature": 15.0,
                    "outdoor_humidity": 60.0,
                    "weather_description": "Нет данных",
                    "timestamp": datetime.now(),
                    "pressure": 1013,
                    "wind_speed": 0,
                    "clouds": 0,
                }

    def _get_weather_description(self, cloud_cover):
        """Описание погоды по облачности"""
        if cloud_cover < 20:
            return "Ясно"
        elif cloud_cover < 50:
            return "Малооблачно"
        elif cloud_cover < 80:
            return "Облачно"
        else:
            return "Пасмурно"

    def test_connection(self):
        """
        Тестирование подключения к API

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            params = {
                "latitude": self.lat,
                "longitude": self.lon,
                "current": "temperature_2m",
                "timezone": "auto"
            }

            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            temp = data["current"]["temperature_2m"]

            return True, f"Подключение успешно! Координаты: {self.lat:.2f}, {self.lon:.2f}, Температура: {temp}°C"

        except requests.exceptions.RequestException as e:
            return False, f"Ошибка подключения: {str(e)}"


if __name__ == "__main__":
    # Тест модуля (не требуется API ключ)
    print("Тест модуля weather_api.py")
    print("Используется Open-Meteo API")

    weather_api = RealWeatherAPI()
    success, message = weather_api.test_connection()
    print(f"\nТест подключения: {message}")

    if success:
        weather = weather_api.get_weather_data()
        print(f"\nДанные о погоде:")
        print(f"  Температура: {weather['outdoor_temperature']}°C")
        print(f"  Влажность: {weather['outdoor_humidity']}%")
        print(f"  Описание: {weather['weather_description']}")
        print(f"  Давление: {weather['pressure']} гПа")
        print(f"  Ветер: {weather['wind_speed']} м/с")
