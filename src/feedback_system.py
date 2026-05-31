"""
Механизм обратной связи
"""
from datetime import datetime


class FeedbackHandler:
    """
    Обработчик обратной связи от пользователя
    """

    # Маппинг фидбека на изменения целевых параметров
    # Значения обоснованы в отчёте НИР (раздел «Эксперименты»):
    # 0.5°C — минимальная ощутимая разница, 1.5°C — сильный дискомфорт (PMV > 0.5)
    FEEDBACK_MAPPING = {
        "very_cold": {"temperature": +1.5, "description": "Очень холодно"},
        "cold": {"temperature": +0.5, "description": "Холодно"},
        "warm": {"temperature": -0.5, "description": "Тепло"},
        "hot": {"temperature": -1.5, "description": "Жарко"},
        "stuffy": {"co2_max": -100, "description": "Душно"},
        "dry": {"humidity": +5.0, "description": "Сухо"},
        "humid": {"humidity": -5.0, "description": "Влажно"},
    }

    def __init__(self):
        self.feedback_history = []

    def process_feedback(self, feedback_type, current_state, target):
        """
        Обработка фидбека - изменение целевых параметров

        Args:
            feedback_type: Тип фидбека (very_cold, cold, warm, hot, stuffy, dry, humid)
            current_state: Текущее состояние среды
            target: Текущие целевые параметры

        Returns:
            dict: Обновленные целевые параметры
        """
        feedback_entry = {
            "timestamp": datetime.now(),
            "type": feedback_type,
            "temperature": current_state.get("temperature"),
            "humidity": current_state.get("humidity"),
            "co2": current_state.get("co2"),
        }
        self.feedback_history.append(feedback_entry)

        # Получаем изменения для данного типа фидбека
        changes = self.FEEDBACK_MAPPING.get(feedback_type, {})

        # Создаем новые целевые параметры
        new_target = target.copy()

        # Применяем изменения
        if "temperature" in changes:
            new_target["temperature"] = target["temperature"] + changes["temperature"]
            # Ограничиваем диапазон 18-28°C
            new_target["temperature"] = max(18.0, min(28.0, new_target["temperature"]))

        if "humidity" in changes:
            new_target["humidity"] = target["humidity"] + changes["humidity"]
            # Ограничиваем диапазон 30-70%
            new_target["humidity"] = max(30.0, min(70.0, new_target["humidity"]))

        if "co2_max" in changes:
            new_target["co2_max"] = target["co2_max"] + changes["co2_max"]
            # Ограничиваем диапазон 600-1200 ppm
            new_target["co2_max"] = max(600, min(1200, new_target["co2_max"]))

        return new_target

    def get_feedback_summary(self):
        """Получение сводки по фидбеку"""
        return {
            "total_feedbacks": len(self.feedback_history),
            "recent": self.feedback_history[-5:] if self.feedback_history else []
        }


if __name__ == "__main__":
    handler = FeedbackHandler()

    current = {"temperature": 24, "humidity": 40, "co2": 600, "illuminance": 300}
    target = {"temperature": 22, "humidity": 50, "co2_max": 800, "illuminance": 300}

    print("Обработка фидбека 'hot':")
    new_target = handler.process_feedback("hot", current, target)
    print(f"  Новая уставка температуры: {new_target['temperature']}°C")

    print("Обработка фидбека 'dry':")
    new_target = handler.process_feedback("dry", current, new_target)
    print(f"  Новая уставка влажности: {new_target['humidity']}%")

    summary = handler.get_feedback_summary()
    print(f"Всего фидбеков: {summary['total_feedbacks']}")
