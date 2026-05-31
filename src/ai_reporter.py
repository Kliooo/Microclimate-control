"""
ИИ-реporter: сбор данных, анализ через OpenRouter (GPT-4o-mini) и отправка в Telegram
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime
import json
import requests
from dotenv import load_dotenv

load_dotenv()

DATA_FOLDER = "simulation_data"
SUBFOLDERS = {
    "microclimate": "microclimate",
    "ai_reports": "ai_reports",
}

MICROCLIMATE_FOLDER = os.path.join(DATA_FOLDER, SUBFOLDERS["microclimate"])
AI_REPORTS_FOLDER = os.path.join(DATA_FOLDER, SUBFOLDERS["ai_reports"])

os.makedirs(AI_REPORTS_FOLDER, exist_ok=True)

REPORT_META_FILE = os.path.join(AI_REPORTS_FOLDER, "last_report_meta.json")


def get_latest_csv_file():
    """Получение последнего CSV файла с данными микроклимата"""
    if not os.path.exists(MICROCLIMATE_FOLDER):
        return None
    
    csv_files = [f for f in os.listdir(MICROCLIMATE_FOLDER) if f.startswith("microclimate_") and f.endswith(".csv")]
    if not csv_files:
        return None
    
    csv_files.sort(reverse=True)
    return os.path.join(MICROCLIMATE_FOLDER, csv_files[0])


def load_period_data(start_time=None):
    """Загрузка данных за период с последнего отчёта"""
    latest_file = get_latest_csv_file()
    if not latest_file:
        return None
    
    df = pd.read_csv(latest_file)
    
    if start_time is None:
        if len(df) < 1440:
            return df
        return df.tail(1440)
    
    df_start = df[df['sim_time'] == start_time]
    if len(df_start) > 0:
        start_idx = df_start.index[0]
        return df.loc[start_idx:].reset_index(drop=True)
    
    return df.tail(1440)


def aggregate_10min(df):
    """Агрегация данных по 10 минут"""
    if df is None or len(df) == 0:
        return []
    
    result = []
    for i in range(0, len(df), 10):
        chunk = df.iloc[i:min(i+10, len(df))]
        if len(chunk) == 0:
            continue
        
        row = {
            "time": chunk["sim_time"].iloc[-1],
            "temperature": round(chunk["temperature"].mean(), 2),
            "humidity": round(chunk["humidity"].mean(), 2),
            "co2": round(chunk["co2"].mean(), 1),
            "illuminance": round(chunk["illuminance"].mean(), 1),
            "pmv": round(chunk["pmv"].mean(), 2),
            "ieq": round(chunk["ieq"].mean(), 1),
            "occupants": round(chunk["occupants"].mean(), 1),
            "outdoor_temp": round(chunk["outdoor_temperature"].mean(), 2),
        }
        result.append(row)
    
    return result


def format_csv_data(data, max_rows=100):
    """Форматирование данных в текстовую таблицу"""
    if not data:
        return "Нет данных"
    
    header = "Время | Температура | Влажность | CO2 | Освещ | PMV | IEQ | Люди | Уличная t"
    rows = [header]
    
    for row in data[:max_rows]:
        rows.append(
            f"{row['time']} | {row['temperature']} | {row['humidity']} | "
            f"{row['co2']} | {row['illuminance']} | {row['pmv']} | "
            f"{row['ieq']} | {row['occupants']} | {row['outdoor_temp']}"
        )
    
    return "\n".join(rows)


def get_time_of_day(sim_hour):
    """Определение времени суток"""
    if 0 <= sim_hour < 6:
        return "ночь"
    elif 6 <= sim_hour < 12:
        return "утро"
    elif 12 <= sim_hour < 18:
        return "день"
    else:
        return "вечер"


def get_devices_stats(history):
    """Получение статистики по устройствам за период"""
    if not history:
        return "Нет данных о работе устройств"
    
    ac_on = sum(1 for h in history if h.get("ac_on", False))
    ac_power = [h.get("ac_power", 0) for h in history if h.get("ac_on", False)]
    
    rad_on = sum(1 for h in history if h.get("radiator_on", False))
    rad_power = [h.get("radiator_power", 0) for h in history if h.get("radiator_on", False)]
    
    hum_on = sum(1 for h in history if h.get("humidifier_on", False))
    hum_power = [h.get("humidifier_power", 0) for h in history if h.get("humidifier_on", False)]
    
    dehum_on = sum(1 for h in history if h.get("dehumidifier_on", False))
    dehum_power = [h.get("dehumidifier_power", 0) for h in history if h.get("dehumidifier_on", False)]
    
    breather_on = sum(1 for h in history if h.get("breather_on", False))
    breather_power = [h.get("breather_power", 0) for h in history if h.get("breather_on", False)]
    
    blinds_pos = [h.get("blinds_pos", 0) for h in history]
    
    total = len(history)
    
    stats = []
    stats.append(f"Кондиционер: {round(ac_on/total*100)}% работы, средняя мощность {round(np.mean(ac_power)) if ac_power else 0}%")
    stats.append(f"Радиатор: {round(rad_on/total*100)}% работы, средняя мощность {round(np.mean(rad_power)) if rad_power else 0}%")
    stats.append(f"Увлажнитель: {round(hum_on/total*100)}% работы, средняя мощность {round(np.mean(hum_power)) if hum_power else 0}%")
    stats.append(f"Осушитель: {round(dehum_on/total*100)}% работы, средняя мощность {round(np.mean(dehum_power)) if dehum_power else 0}%")
    stats.append(f"Бризер: {round(breather_on/total*100)}% работы, средняя мощность {round(np.mean(breather_power)) if breather_power else 0}%")
    stats.append(f"Шторы: средняя закрытость {round(np.mean(blinds_pos)) if blinds_pos else 0}%")
    
    return "\n".join(stats)


def compute_key_points(data):
    """Выборка 5-7 ключевых точек: начало, конец, экстремумы, резкие скачки"""
    if not data:
        return "Нет данных"
    n = len(data)
    if n <= 7:
        return format_csv_data(data, max_rows=n)

    temps = [r["temperature"] for r in data]
    co2s = [r["co2"] for r in data]
    pmvs = [r["pmv"] for r in data]

    candidates = {0, n - 1,
                  int(np.argmax(co2s)),
                  int(np.argmax(temps)),
                  int(np.argmax(pmvs)),
                  int(np.argmin(pmvs))}

    for i in range(1, n):
        if abs(data[i]["pmv"] - data[i - 1]["pmv"]) > 0.3:
            candidates.add(i)
        if abs(data[i]["co2"] - data[i - 1]["co2"]) > 300:
            candidates.add(i)

    priority = {0, n - 1,
                int(np.argmax(co2s)),
                int(np.argmax(temps)),
                int(np.argmax(pmvs)),
                int(np.argmin(pmvs))}

    selected = sorted(priority)
    for c in sorted(candidates):
        if c not in priority and len(selected) < 7:
            selected.append(c)
            selected.sort()
    if len(selected) < 7:
        for c in sorted(candidates):
            if c not in selected:
                selected.append(c)
                selected.sort()
                if len(selected) >= 7:
                    break
    selected = selected[:7]

    lines = []
    for i in selected:
        r = data[i]
        line = (f"{r['time']} | {r['temperature']:.1f}°C | {r['humidity']:.0f}% | "
                f"{r['co2']:.0f} ppm | PMV {r['pmv']:.2f} | {r.get('occupants', 0):.0f} чел.")
        if i == int(np.argmax(co2s)):
            line += " ← макс CO₂"
        elif i == int(np.argmax(temps)):
            line += " ← макс T"
        elif i == int(np.argmax(pmvs)):
            line += " ← макс PMV"
        elif i == int(np.argmin(pmvs)):
            line += " ← мин PMV"
        lines.append(line)
    return "\n".join(lines)


def load_previous_data():
    """Загрузка данных прошлого отчёта"""
    if not os.path.exists(REPORT_META_FILE):
        return None
    
    try:
        with open(REPORT_META_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return None


def save_report_meta(end_time, start_time, season, time_of_day, target, data, devices_stats, report):
    """Сохранение метаданных отчёта"""
    meta = {
        "time": end_time,
        "period": f"{start_time} - {end_time}",
        "start_time": start_time,
        "end_time": end_time,
        "season": season,
        "time_of_day": time_of_day,
        "target": target,
        "data": data,
        "devices": devices_stats,
        "report": report
    }
    
    with open(REPORT_META_FILE, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def create_prompt(prev_meta, curr_data, start_time, end_time, season, time_of_day, target, devices_stats):
    """Создание промпта для AI"""
    if not curr_data:
        return "Нет данных для анализа"

    temps = [r["temperature"] for r in curr_data]
    hums = [r["humidity"] for r in curr_data]
    co2s = [r["co2"] for r in curr_data]
    pmvs = [r["pmv"] for r in curr_data]
    ieqs = [r["ieq"] for r in curr_data]
    lums = [r["illuminance"] for r in curr_data]

    avg_t = float(np.mean(temps))
    min_t = float(np.min(temps))
    max_t = float(np.max(temps))
    min_t_i = int(np.argmin(temps))
    max_t_i = int(np.argmax(temps))
    min_t_time = curr_data[min_t_i]["time"]
    max_t_time = curr_data[max_t_i]["time"]

    avg_rh = float(np.mean(hums))
    min_rh = float(np.min(hums))
    max_rh = float(np.max(hums))

    avg_co2 = float(np.mean(co2s))
    min_co2 = float(np.min(co2s))
    max_co2 = float(np.max(co2s))
    min_co2_i = int(np.argmin(co2s))
    max_co2_i = int(np.argmax(co2s))
    min_co2_time = curr_data[min_co2_i]["time"]
    max_co2_time = curr_data[max_co2_i]["time"]

    avg_pmv = float(np.mean(pmvs))
    min_pmv = float(np.min(pmvs))
    max_pmv = float(np.max(pmvs))

    avg_ieq = float(np.mean(ieqs))
    avg_lux = float(np.mean(lums))

    half = len(curr_data) // 2
    if half > 0:
        def trend_diff(label):
            a = np.mean([r[label] for r in curr_data[:half]])
            b = np.mean([r[label] for r in curr_data[half:]])
            return b - a

        def trend_str(diff, unit=""):
            direction = "рост" if diff > 0 else "снижение"
            return f"{direction} на {abs(diff):.1f}{unit}"

        temp_trend = trend_str(trend_diff("temperature"), "°C")
        rh_trend = trend_str(trend_diff("humidity"), "%")
        co2_trend = trend_str(trend_diff("co2"), " ppm")
        pmv_trend = trend_str(trend_diff("pmv"), "")
    else:
        temp_trend = rh_trend = co2_trend = pmv_trend = "недостаточно данных"

    n = len(curr_data)
    pmv_hi = sum(1 for r in curr_data if r["pmv"] > 0.5)
    co2_1k = sum(1 for r in curr_data if r["co2"] > 1000)
    co2_15 = sum(1 for r in curr_data if r["co2"] > 1500)
    rh_hi = sum(1 for r in curr_data if r["humidity"] > 60)

    pmv_violation_time = pmv_hi * 10
    pmv_violation_percent = round(pmv_hi / n * 100) if n else 0
    co2_1000_time = co2_1k * 10
    co2_1500_time = co2_15 * 10
    rh_violation_time = rh_hi * 10

    key_points = compute_key_points(curr_data)

    prev_str = ""
    if prev_meta and prev_meta.get("report"):
        prev_str = f"Предыдущий анализ ({prev_meta.get('period', '?')}):\n{prev_meta['report']}"
    elif prev_meta and prev_meta.get("data"):
        prev_str = f"Предыдущий период ({prev_meta.get('period', '?')}): были данные"
    else:
        prev_str = ""

    prompt = f"""Ты — строгий русский эксперт по микроклимату помещений с 15-летним опытом (теплотехника, СНиП, ASHRAE, EN 16798).

Проанализируй предоставленные данные и дай профессиональную оценку состояния микроклимата.

МЕТАДАННЫЕ:
Период: {start_time} – {end_time} ({season}, {time_of_day})

ЦЕЛЬ: Температура {target.get('temperature', 22)}°C, Влажность {target.get('humidity', 50)}%, CO₂ ≤ {target.get('co2_max', 800)} ppm

СВОДКА:
• Температура: средн. {avg_t:.1f}°C (мин {min_t:.1f} в {min_t_time}, макс {max_t:.1f} в {max_t_time})
• Относительная влажность: средн. {avg_rh:.0f}% (мин {min_rh:.0f}, макс {max_rh:.0f})
• CO₂: средн. {avg_co2:.0f} ppm (мин {min_co2:.0f} в {min_co2_time}, макс {max_co2:.0f} в {max_co2_time})
• PMV: средн. {avg_pmv:.2f} (мин {min_pmv:.2f}, макс {max_pmv:.2f})
• IEQ: средн. {avg_ieq:.0f}%
• Освещённость: средн. {avg_lux:.0f} люкс

ТРЕНДЫ ЗА ПЕРИОД:
• Температура: {temp_trend}
• Влажность: {rh_trend}
• CO₂: {co2_trend}
• PMV: {pmv_trend}

КРИТИЧЕСКИЕ НАРУШЕНИЯ:
• PMV > +0.5: {pmv_violation_time} мин ({pmv_violation_percent}%)
• CO₂ > 1000 ppm: {co2_1000_time} мин
• CO₂ > 1500 ppm: {co2_1500_time} мин
• Влажность > 60%: {rh_violation_time} мин

РАБОТА ОБОРУДОВАНИЯ:
{devices_stats}

КЛЮЧЕВЫЕ ТОЧКИ ДАННЫХ (самые показательные):
{key_points}

{prev_str}

НОРМЫ:
- Температура: 20–26°C
- Влажность: 40–60%
- CO₂: <1000 — хорошо, 1000–1500 — удовлетворительно, >1500 — плохо
- PMV: −0.5…+0.5 — норма категории A

ОТВЕТЬ ТОЛЬКО В СЛЕДУЮЩЕМ ФОРМАТЕ, на чистом русском языке, по 2–4 предложения на пункт. Каждый пункт обязан ссылаться на данные выше. Без лишней воды.

1. Оценка PMV и теплового комфорта — сошлитесь на среднее/мин/макс PMV. Если PMV в норме (−0.5…+0.5), просто констатируйте комфортные условия.
2. Динамика и основные проблемы за период — какие параметры вышли за норму, как менялись. Если все параметры в пределах нормы, напишите «существенных отклонений нет».
3. Критические аномалии и их вероятные причины — если параметры в пределах нормы (CO₂ < 1000 ppm, влажность 40–60%, PMV −0.5…+0.5, температура 20–26°C), напишите «критических аномалий не обнаружено». Если есть отклонения, укажите, какие устройства не работали (или работали неправильно) и как это привело к аномалиям. НЕ КРИТИКУЙТЕ устройства, если параметры в норме — кондиционер может не работать, потому что охлаждение не требуется.
4. Конкретные рекомендации (что делать в первую очередь) — что включить/настроить, с учётом текущей работы оборудования. Если система работает штатно, напишите «система работает штатно, вмешательство не требуется».
"""
    return prompt


def send_to_ai(prompt):
    """Отправка запроса в OpenRouter (GPT-4o-mini)"""
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

    if not api_key:
        return "Ошибка: не указан OPENROUTER_API_KEY в .env"

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Ты русский эксперт по микроклимату."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 600,
        "temperature": 0.2,
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=180)
        if response.status_code == 200:
            data = response.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
        else:
            return f"Ошибка AI: {response.status_code}"
    except Exception as e:
        return f"Исключение AI: {str(e)}"


def send_to_telegram(message):
    """Отправка сообщения в Telegram"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        return "Ошибка: не найдены TOKEN или CHAT_ID"
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            return "Сообщение отправлено успешно"
        else:
            return f"Ошибка отправки: {response.status_code}"
    except Exception as e:
        return f"Исключение: {str(e)}"


def generate_daily_report(start_time=None, end_time=None, season="зима", target=None, history=None):
    """Генерация отчёта за период"""
    if end_time is None:
        end_time = "??:??"

    df = load_period_data(start_time)

    if df is None or len(df) == 0:
        return "Нет данных для анализа"

    curr_data = aggregate_10min(df)
    prev_meta = load_previous_data()

    time_of_day = get_time_of_day(int(end_time.split(":")[0]) if ":" in end_time else 12)

    if target is None:
        target = {"temperature": 22, "humidity": 50, "co2_max": 800, "illuminance": 300}

    if history is None:
        history = []

    devices_stats = get_devices_stats(history)

    prompt = create_prompt(
        prev_meta, curr_data,
        start_time or df["sim_time"].iloc[0],
        end_time,
        season, time_of_day, target, devices_stats
    )

    ai_response = send_to_ai(prompt)

    if "Ошибка" in ai_response or "Исключение" in ai_response or not ai_response:
        ai_response = "Не удалось получить ответ от AI."
        ai_source = "Ошибка AI"
    else:
        ai_source = "GPT-4o-mini"

    agg_data = {
        "temperature": {"avg": round(df["temperature"].mean(), 2), "min": round(df["temperature"].min(), 2), "max": round(df["temperature"].max(), 2)},
        "humidity": {"avg": round(df["humidity"].mean(), 2)},
        "co2": {"avg": round(df["co2"].mean(), 1)},
        "illuminance": {"avg": round(df["illuminance"].mean(), 1)},
        "pmv": {"avg": round(df["pmv"].mean(), 2)},
        "ieq": {"avg": round(df["ieq"].mean(), 1)},
        "period": f"{start_time or df['sim_time'].iloc[0]} - {end_time}"
    }

    pmv_avg = agg_data["pmv"]["avg"]
    ppd_avg = round(100 - 95 * np.exp(-0.03353 * pmv_avg**4 - 0.2179 * pmv_avg**2), 1)

    header = f"📊 Отчёт ({agg_data['period']})\n\n"
    stats = (
        f"🎯 PMV: {agg_data['pmv']['avg']}\n"
        f"📈 IEQ: {agg_data['ieq']['avg']}%\n"
        f"🌡️ Температура: {agg_data['temperature']['avg']}°C "
        f"(мин: {agg_data['temperature']['min']}, макс: {agg_data['temperature']['max']})\n"
        f"💧 Влажность: {agg_data['humidity']['avg']}%\n"
        f"🌬️ CO2: {agg_data['co2']['avg']} ppm\n"
        f"💡 Освещённость: {agg_data['illuminance']['avg']} люкс\n"
        f"😞 PPD: {ppd_avg}%\n"
    )

    full_message = (
        header + stats +
        f"\n⚙️ Работа устройств:\n{devices_stats}\n\n"
        f"🤖 Анализ ({ai_source}):\n{ai_response}"
    )

    result = send_to_telegram(full_message)

    save_report_meta(
        end_time,
        start_time or df["sim_time"].iloc[0],
        season, time_of_day, target, curr_data, devices_stats, ai_response
    )

    return f"Данные обработаны. {result}"


if __name__ == "__main__":
    print("Генерация отчёта...")
    result = generate_daily_report()
    print(result)