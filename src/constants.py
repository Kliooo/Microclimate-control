"""
Модуль констант и стандартов для системы управления микроклиматом
"""
import numpy as np

# ГОСТ 30494-2011 Класс B - Предельные значения параметров микроклимата
GOST_LIMITS = {
    "temperature_winter": {"min": 20.0, "max": 24.0},  # Зима: 20-24°C
    "temperature_summer": {"min": 22.0, "max": 26.0},  # Лето: 22-26°C
    "humidity": {"min": 40.0, "max": 60.0},            # Влажность: 40-60%
    "co2": {"max": 1000},                              # CO2: < 1000 ppm
    "illuminance_general": {"min": 150},               # Освещенность общая: > 150 лк
    "illuminance_work": {"min": 300},                  # Рабочая зона: > 300 лк

}

# Ограничения на разовые изменения (безопасность)
CHANGE_LIMITS = {
    "temperature": 2.0,    # ±2°C за раз
    "humidity": 20.0,      # ±20% за раз
    "air_speed": 0.2,      # ±0.2 м/с
}

# PMV шкала оценки
PMV_SCALE = {
    -3: "Очень холодно",
    -2: "Холодно",
    -1: "Прохладно",
    0: "Нейтрально",
    1: "Тепло",
    2: "Жарко",
    3: "Очень жарко",
}

# Целевые параметры по умолчанию
DEFAULT_TARGET = {
    "temperature": 22.0,
    "humidity": 50.0,
    "co2_max": 800,
    "illuminance": 300,
}

# Весовые коэффициенты для IEQ
IEQ_WEIGHTS = {
    "thermal": 0.45,      # Термальный комфорт
    "air_quality": 0.35,  # Качество воздуха
    "visual": 0.20,       # Визуальный комфорт
}

# Время нормализации данных (в минутах)
NORMALIZATION_WINDOW = 10  # 10-минутное скользящее окно

# Физические константы для расчета PMV
PMV_CONSTANTS = {
    "metabolism_seated": 1.0,    # Метаболизм сидя (met)
    "clothing_inside_winter": 1.0,  # Теплопроводность одежды зимой (clo)
    "clothing_inside_summer": 0.5,  # Летом
}

# Пороговые значения для расчета суб-индексов
INDEX_THRESHOLDS = {
    "co2": {"good": 600, "acceptable": 800, "poor": 1000, "bad": 1500},
    "illuminance": {"good": 300, "acceptable": 200, "poor": 100},
}
