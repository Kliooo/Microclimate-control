"""
Симулятор системы управления микроклиматом
Streamlit UI
"""
import streamlit as st
import numpy as np
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go
import time
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.sensor_generator import SensorDataGenerator, ExternalEnvironmentSimulator
from src.central_hub import DataNormalizer, PMVCalculator, IEQCalculator, SafetyChecker
from src.devices import DeviceController
from src.feedback_system import FeedbackHandler
from src.constants import DEFAULT_TARGET, GOST_LIMITS, CHANGE_LIMITS, PMV_SCALE
from src.weather_api import RealWeatherAPI
import streamlit_folium as st_folium
import folium
from src.ai_reporter import generate_daily_report

DATA_FOLDER = "simulation_data"
SUBFOLDERS = {
    "microclimate": "microclimate",
    "feedback": "feedback"
}

for subfolder in SUBFOLDERS.values():
    path = os.path.join(DATA_FOLDER, subfolder)
    if not os.path.exists(path):
        os.makedirs(path)

st.set_page_config(
    page_title="Симулятор Микроклимата",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)

if "initialized" not in st.session_state:
    st.session_state.initialized = True
    st.session_state.simulation_running = False
    st.session_state.simulation_speed = 15
    st.session_state.step_count = 0
    st.session_state.chart_update_frequency = 50

    # Симуляция времени (начинаем с 6:00)
    st.session_state.sim_hour = 6
    st.session_state.sim_minute = 0

    st.session_state.sensor_gen = SensorDataGenerator(seed=42)
    st.session_state.outdoor_sim = ExternalEnvironmentSimulator(seed=42)
    st.session_state.normalizer = DataNormalizer(window_minutes=10)
    st.session_state.pmv_calc = PMVCalculator()
    st.session_state.ieq_calc = IEQCalculator()
    st.session_state.safety_checker = SafetyChecker()
    st.session_state.device_controller = DeviceController()
    st.session_state.feedback_handler = FeedbackHandler()

    st.session_state.target = DEFAULT_TARGET.copy()
    st.session_state.history = []
    st.session_state.history_limit = 1440
    st.session_state.csv_filenames = {
        "microclimate": None,
        "feedback": None
    }
    st.session_state.ai_log = []
    st.session_state.feedback_log = []
    st.session_state.last_ai_report_hour = None
    st.session_state.last_report_sent = False
    st.session_state.report_status = ""

    # Настройки для реальных данных погоды
    st.session_state.weather_mode = "simulation"
    st.session_state.latitude = 59.9311
    st.session_state.longitude = 30.3609
    st.session_state.real_weather_api = None
    st.session_state.api_connected = False



def save_microclimate_csv(data_list):
    """Сохранение данных микроклимата в CSV (дописывание новых записей)"""
    if not data_list:
        return None

    if st.session_state.get("csv_filenames", {}).get("microclimate") is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"microclimate_{timestamp}.csv"
        st.session_state.csv_filenames["microclimate"] = os.path.join(
            DATA_FOLDER, SUBFOLDERS["microclimate"], filename
        )

    filepath = st.session_state.csv_filenames["microclimate"]

    last_entry = data_list[-1]
    df_row = pd.DataFrame([last_entry])

    if not os.path.exists(filepath):
        df_row.to_csv(filepath, index=False, encoding='utf-8-sig')
    else:
        df_row.to_csv(filepath, mode='a', header=False, index=False, encoding='utf-8-sig')

    return filepath


def save_feedback(feedback_type, previous_target, new_target, current_state):
    """Сохранение фидбека пользователя в CSV"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "feedback_type": feedback_type,
        "previous_temp": previous_target.get("temperature"),
        "new_temp": new_target.get("temperature"),
        "previous_humidity": previous_target.get("humidity"),
        "new_humidity": new_target.get("humidity"),
        "current_temp": current_state.get("temperature"),
        "current_humidity": current_state.get("humidity"),
        "current_co2": current_state.get("co2"),
        "current_pmv": current_state.get("pmv"),
        "temp_adjustment": new_target.get("temperature") - previous_target.get("temperature"),
        "humidity_adjustment": new_target.get("humidity") - previous_target.get("humidity"),
    }
    st.session_state.feedback_log.append(entry)

    if st.session_state.get("csv_filenames", {}).get("feedback") is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"feedback_{timestamp}.csv"
        st.session_state.csv_filenames["feedback"] = os.path.join(
            DATA_FOLDER, SUBFOLDERS["feedback"], filename
        )

    df = pd.DataFrame(st.session_state.feedback_log)
    df.to_csv(st.session_state.csv_filenames["feedback"], index=False, encoding='utf-8-sig')
    return st.session_state.csv_filenames["feedback"]


def reset_simulation():
    """Сброс симуляции"""
    st.session_state.step_count = 0
    st.session_state.simulation_running = False
    st.session_state.sim_hour = 8
    st.session_state.sim_minute = 0
    st.session_state.normalizer.clear()
    st.session_state.history = []
    st.session_state.target = DEFAULT_TARGET.copy()
    st.session_state.feedback_handler = FeedbackHandler()
    st.session_state.device_controller = DeviceController()
    st.session_state.csv_filenames = {
        "microclimate": None,
        "feedback": None
    }
    st.session_state.ai_log = []
    st.session_state.feedback_log = []
    st.session_state.last_ai_report_hour = None
    st.session_state.last_report_sent = False
    st.session_state.report_status = ""

    st.session_state.sensor_gen = SensorDataGenerator(seed=42)
    st.session_state.outdoor_sim = ExternalEnvironmentSimulator(seed=42)


def simulation_step():
    """Выполнение одного шага симуляции (1 минута модельного времени)"""
    hour = st.session_state.sim_hour
    minute = st.session_state.sim_minute

    st.session_state.sim_minute += 1
    if st.session_state.sim_minute >= 60:
        st.session_state.sim_minute = 0
        st.session_state.sim_hour = (st.session_state.sim_hour + 1) % 24

    if st.session_state.get("auto_control_enabled", False) and len(st.session_state.history) > 0:
        last_state = st.session_state.history[-1]
        st.session_state.device_controller.auto_control(last_state, st.session_state.target)

    device_state = st.session_state.device_controller.get_device_state()

    current_reading = st.session_state.sensor_gen.generate_readings(
        hour=hour, minute=minute, device_state=device_state
    )

    normalized = st.session_state.normalizer.get_normalized(current_reading)

    ieq_report = st.session_state.ieq_calc.get_ieq_report(
        temperature=current_reading["temperature"],
        humidity=current_reading["humidity"],
        co2=current_reading["co2"],
        illuminance=current_reading["illuminance"],
    )

    if st.session_state.weather_mode == "real" and st.session_state.real_weather_api:
        weather = st.session_state.real_weather_api.get_weather_data()
        outdoor_temp = weather["outdoor_temperature"]
        outdoor_hum = weather["outdoor_humidity"]
    else:
        outdoor_temp = current_reading.get("outdoor_temperature", 0)
        outdoor_hum = current_reading.get("outdoor_humidity", 50)

    history_entry = {
        "timestamp": current_reading["timestamp"],
        "sim_time": f"{hour:02d}:{minute:02d}",
        "temperature": current_reading["temperature"],
        "humidity": current_reading["humidity"],
        "co2": current_reading["co2"],
        "illuminance": current_reading["illuminance"],
        "outdoor_temperature": outdoor_temp,
        "outdoor_humidity": outdoor_hum,
        "target_temperature": st.session_state.target["temperature"],
        "target_humidity": st.session_state.target["humidity"],
        "pmv": ieq_report["pmv"],
        "ppd": ieq_report["ppd"],
        "ieq": ieq_report["overall_ieq"],
        "thermal_index": ieq_report["thermal_index"],
        "air_quality_index": ieq_report["air_quality_index"],
        "visual_index": ieq_report["visual_index"],
        "occupants": current_reading.get("occupants", 0),
    }

    st.session_state.history.append(history_entry)
    if len(st.session_state.history) > st.session_state.history_limit:
        st.session_state.history.pop(0)

    st.session_state.step_count += 1

    save_microclimate_csv(st.session_state.history)

    current_time_str = f"{st.session_state.sim_hour:02d}:{st.session_state.sim_minute:02d}"
    auto_times = st.session_state.get("auto_report_times", ["08:00", "12:00", "18:00"])
    
    history_entry["ac_on"] = device_state["ac_active"]
    history_entry["ac_power"] = round(device_state["ac_intensity"] * 100)
    history_entry["radiator_on"] = device_state["radiator_active"]
    history_entry["radiator_power"] = round(device_state["radiator_intensity"] * 100)
    history_entry["humidifier_on"] = device_state["humidifier_active"]
    history_entry["humidifier_power"] = round(device_state["humidifier_intensity"] * 100)
    history_entry["dehumidifier_on"] = device_state["dehumidifier_active"]
    history_entry["dehumidifier_power"] = round(device_state["dehumidifier_intensity"] * 100)
    history_entry["breather_on"] = device_state["breather_active"]
    history_entry["breather_power"] = round(device_state["breather_intensity"] * 100)
    history_entry["blinds_pos"] = round(device_state["blinds_intensity"] * 100)
    
    if current_time_str in auto_times and current_time_str != st.session_state.get("last_ai_report_time"):
        try:
            last_time = st.session_state.get("last_ai_report_time")
            season = st.session_state.sensor_gen.cfg["climate"]["season"]
            target = st.session_state.target.copy()
            result = generate_daily_report(last_time, current_time_str, season, target, st.session_state.history)
            st.session_state.last_ai_report_time = current_time_str
        except Exception as e:
            pass

    return history_entry, ieq_report, {"outdoor_temperature": outdoor_temp, "outdoor_humidity": outdoor_hum}


def create_separate_charts():
    """Создание отдельных графиков для каждого параметра"""
    if len(st.session_state.history) < 2:
        return None

    df = pd.DataFrame(st.session_state.history)

    legend_cfg = dict(x=0, y=1.00, orientation="h", xanchor="left", yanchor="top")

    target_temp = df["target_temperature"].iloc[-1]
    temp_min = min(df["temperature"].min(), df["outdoor_temperature"].min(), target_temp) - 2
    temp_max = max(df["temperature"].max(), df["outdoor_temperature"].max(), target_temp) + 2
    temp_range = temp_max - temp_min
    temp_center = target_temp
    temp_y_min = temp_center - temp_range / 2
    temp_y_max = temp_center + temp_range / 2

    st.plotly_chart(
        go.Figure(data=[
            go.Scatter(x=df.index, y=df["temperature"], name="В помещении", line=dict(color="#e74c3c", width=2)),
            go.Scatter(x=df.index, y=df["outdoor_temperature"], name="На улице", line=dict(color="#e67e22", width=2)),
            go.Scatter(x=df.index, y=df["target_temperature"], name="Целевая", line=dict(color="#c0392b", width=2, dash="dash")),
        ]).update_layout(
            title="Температура (C)",
            height=220,
            margin=dict(t=30, b=45, l=40, r=10),
            legend=legend_cfg,
            yaxis=dict(range=[temp_y_min, temp_y_max])
        ),
        width='stretch'
    )

    target_hum = df["target_humidity"].iloc[-1]
    hum_min = min(df["humidity"].min(), df["outdoor_humidity"].min(), target_hum) - 5
    hum_max = max(df["humidity"].max(), df["outdoor_humidity"].max(), target_hum) + 5
    hum_range = hum_max - hum_min
    hum_center = target_hum
    hum_y_min = hum_center - hum_range / 2
    hum_y_max = hum_center + hum_range / 2

    st.plotly_chart(
        go.Figure(data=[
            go.Scatter(x=df.index, y=df["humidity"], name="В помещении", line=dict(color="#12e23f", width=2)),
            go.Scatter(x=df.index, y=df["outdoor_humidity"], name="На улице", line=dict(color="#e67e22", width=2)),
            go.Scatter(x=df.index, y=df["target_humidity"], name="Целевая", line=dict(color="#2980b9", width=2, dash="dash")),
        ]).update_layout(
            title="Влажность (%)",
            height=220,
            margin=dict(t=30, b=45, l=40, r=10),
            legend=legend_cfg,
            yaxis=dict(range=[hum_y_min, hum_y_max])
        ),
        width='stretch'
    )

    fig_pmv = go.Figure(data=[
        go.Scatter(x=df.index, y=df["pmv"], name="PMV", line=dict(color="#9b59b6", width=2)),
    ])
    fig_pmv.add_hline(y=0, line_dash="dash", line_color="gray")
    fig_pmv.add_hline(y=0.5, line_dash="dot", line_color="green", opacity=0.5)
    fig_pmv.add_hline(y=-0.5, line_dash="dot", line_color="green", opacity=0.5)
    fig_pmv.update_layout(title="PMV", height=200, margin=dict(t=30, b=10, l=40, r=10),
                         yaxis=dict(range=[-3, 3]), showlegend=False)
    st.plotly_chart(fig_pmv, width='stretch')

    st.plotly_chart(
        go.Figure(data=[
            go.Scatter(x=df.index, y=df["co2"], name="CO2", line=dict(color="#f39c12", width=2)),
        ]).update_layout(title="CO2 (ppm)", height=200, margin=dict(t=30, b=10, l=40, r=10), showlegend=False),
        width='stretch'
    )

    st.plotly_chart(
        go.Figure(data=[
            go.Scatter(x=df.index, y=df["illuminance"], name="Освещенность", line=dict(color="#f1c40f", width=2)),
        ]).update_layout(title="Освещенность (люкс)", height=200, margin=dict(t=30, b=10, l=40, r=10), showlegend=False),
        width='stretch'
    )

    return True


def main():
    st.title("Симулятор системы управления микроклиматом")
    st.markdown("---")

    with st.sidebar:
        st.header("Управление и настройки")

        col1, col2 = st.columns(2)
        with col1:
            is_running = st.session_state.simulation_running
            if st.button(
                "Запустить",
                type="primary",
                disabled=is_running,
                width='stretch'
            ):
                st.session_state.simulation_running = True
                st.rerun()
        with col2:
            if st.button(
                "Остановить",
                type="secondary",
                disabled=not is_running,
                width='stretch'
            ):
                st.session_state.simulation_running = False
                st.rerun()

        st.markdown("")

        speed = st.slider(
            "Скорость симуляции (шагов/сек)",
            min_value=1,
            max_value=30,
            value=st.session_state.simulation_speed,
            step=1,
            help=None
        )
        st.session_state.simulation_speed = speed

        chart_freq = st.number_input(
            "Частота обновления графика (раз в N шагов)",
            min_value=1,
            max_value=200,
            value=st.session_state.chart_update_frequency,
            step=1,
            help="График будет обновляться каждые N шагов симуляции"
        )
        st.session_state.chart_update_frequency = chart_freq

        st.markdown("")

        if st.button("Сбросить симуляцию", width='stretch'):
            reset_simulation()
            st.rerun()

        st.markdown("---")

        st.markdown("")
        st.subheader("ИИ-отчёты")

        col1, col2 = st.columns([2, 1])
        with col1:
            if st.button("Отправить отчёт", width='stretch', type="primary"):
                with st.spinner("Генерирую отчёт..."):
                    try:
                        last_time = st.session_state.get("last_ai_report_time")
                        current_time = f"{st.session_state.sim_hour:02d}:{st.session_state.sim_minute:02d}"
                        season = st.session_state.sensor_gen.cfg["climate"]["season"]
                        target = st.session_state.target.copy()
                        result = generate_daily_report(last_time, current_time, season, target, st.session_state.history)
                        st.session_state.last_ai_report_time = current_time
                    except Exception as e:
                        st.error(f"Ошибка: {str(e)}")
        
        last_report_text = st.session_state.get("last_ai_report_time", "—")
        with col2:
            st.markdown(f"<div style='text-align: center; padding: 8px; font-size: 0.9em;'>Последний отчёт: {last_report_text}</div>", unsafe_allow_html=True)

        st.markdown("**Автоотправка:**")
        
        cols = st.columns(3)
        if "auto_report_times" not in st.session_state:
            st.session_state.auto_report_times = ["08:00", "12:00", "18:00"]
        
        time_options = [f"{h:02d}:{m:02d}" for h in range(24) for m in [0, 15, 30, 45]]
        
        for i in range(3):
            with cols[i]:
                idx = time_options.index(st.session_state.auto_report_times[i]) if st.session_state.auto_report_times[i] in time_options else 0
                selected = st.selectbox("Время", time_options, index=idx, key=f"auto_time_{i}")
                st.session_state.auto_report_times[i] = selected

        st.markdown(f"**Модельное время:** {st.session_state.sim_hour:02d}:{st.session_state.sim_minute:02d}")
        st.markdown(f"**Шаг:** {st.session_state.step_count}")

        st.markdown("---")

        st.subheader("Целевые параметры")

        season_options = {"winter": "Зима", "spring": "Весна",
                          "summer": "Лето", "autumn": "Осень"}
        cfg = st.session_state.sensor_gen.cfg
        current_season = cfg["climate"]["season"]
        season = st.selectbox(
            "Сезон",
            options=list(season_options.keys()),
            format_func=lambda x: season_options[x],
            index=list(season_options.keys()).index(current_season),
            key="season_select"
        )
        if season != current_season:
            st.session_state.sensor_gen.set_season(season)
            st.session_state.outdoor_sim = ExternalEnvironmentSimulator(seed=42)

        if "slider_temp_value" not in st.session_state:
            st.session_state.slider_temp_value = st.session_state.target.get("temperature", 22)
        if "slider_humidity_value" not in st.session_state:
            st.session_state.slider_humidity_value = st.session_state.target.get("humidity", 50)
        if "slider_co2_value" not in st.session_state:
            st.session_state.slider_co2_value = st.session_state.target.get("co2_max", 800)
        if "slider_illuminance_value" not in st.session_state:
            st.session_state.slider_illuminance_value = st.session_state.target.get("illuminance", 300)

        st.session_state.slider_temp_value = st.session_state.target.get("temperature", 22)
        st.session_state.slider_humidity_value = st.session_state.target.get("humidity", 50)
        st.session_state.slider_co2_value = st.session_state.target.get("co2_max", 800)
        st.session_state.slider_illuminance_value = st.session_state.target.get("illuminance", 300)

        def update_temp():
            st.session_state.target["temperature"] = st.session_state.target_temp_slider
            st.session_state.slider_temp_value = st.session_state.target_temp_slider

        def update_humidity():
            st.session_state.target["humidity"] = st.session_state.target_humidity_slider
            st.session_state.slider_humidity_value = st.session_state.target_humidity_slider

        def update_co2():
            st.session_state.target["co2_max"] = st.session_state.target_co2_slider
            st.session_state.slider_co2_value = st.session_state.target_co2_slider

        def update_illuminance():
            st.session_state.target["illuminance"] = st.session_state.target_illuminance_slider
            st.session_state.slider_illuminance_value = st.session_state.target_illuminance_slider

        st.slider(
            "Температура (C)",
            min_value=16.0,
            max_value=30.0,
            value=float(st.session_state.slider_temp_value),
            step=0.5,
            key="target_temp_slider",
            on_change=update_temp
        )

        st.slider(
            "Влажность (%)",
            min_value=20.0,
            max_value=80.0,
            value=float(st.session_state.slider_humidity_value),
            step=1.0,
            key="target_humidity_slider",
            on_change=update_humidity
        )

        st.slider(
            "Порог CO2 (ppm)",
            min_value=400,
            max_value=1500,
            value=int(st.session_state.slider_co2_value),
            step=50,
            key="target_co2_slider",
            on_change=update_co2
        )

        st.slider(
            "Освещенность (люкс)",
            min_value=100,
            max_value=600,
            value=int(st.session_state.slider_illuminance_value),
            step=25,
            key="target_illuminance_slider",
            on_change=update_illuminance
        )

    col_center, col_right = st.columns([3, 1])

    with col_center:
        st.subheader("Текущие параметры")

        if len(st.session_state.history) > 0:
            last = st.session_state.history[-1]

            metrics_row1 = st.columns(5)
            with metrics_row1[0]:
                st.metric("IEQ Score", f"{last.get('ieq', 0):.1f}%")
            with metrics_row1[1]:
                st.metric("Температура", f"{last['temperature']:.1f} C",
                         delta=f"{last['temperature'] - last.get('target_temperature', 22):.1f}")
            with metrics_row1[2]:
                st.metric("Влажность", f"{last['humidity']:.1f}%",
                         delta=f"{last['humidity'] - last.get('target_humidity', 50):.1f}")
            with metrics_row1[3]:
                st.metric("CO2", f"{last['co2']:.0f} ppm")
            with metrics_row1[4]:
                st.metric("Освещенность", f"{last['illuminance']:.0f} люкс")

            st.markdown("")

            metrics_row2 = st.columns(5)
            with metrics_row2[0]:
                st.metric("Термальный", f"{last.get('thermal_index', 0):.1f}")
            with metrics_row2[1]:
                st.metric("Воздух", f"{last.get('air_quality_index', 0):.1f}")
            with metrics_row2[2]:
                st.metric("Визуальный", f"{last.get('visual_index', 0):.1f}")
            with metrics_row2[3]:
                pmv_val = last['pmv']
                pmv_desc = PMV_SCALE.get(int(round(pmv_val)), "Нейтрально")
                st.metric("PMV", f"{pmv_val:.2f}", delta=pmv_desc)
            with metrics_row2[4]:
                st.metric("PPD", f"{last.get('ppd', 0):.1f}%")

        st.markdown("---")

        st.subheader("Динамика изменения параметров")

        if len(st.session_state.history) > 5:
            if (not st.session_state.simulation_running or
                st.session_state.step_count % st.session_state.chart_update_frequency == 0):
                create_separate_charts()
        else:
            st.info("Накапливаю данные для отображения графиков...")

    with col_right:
        st.subheader("Обратная связь")

        st.markdown("**Температура**")
        temp_buttons = [
            ("Оч холодно", "very_cold"),
            ("Холодно", "cold"),
            ("Тепло", "warm"),
            ("Жарко", "hot"),
        ]

        temp_row1 = st.columns(2)
        for i in range(2):
            label, fb_type = temp_buttons[i]
            with temp_row1[i]:
                if st.button(label, key=f"fb_{fb_type}", use_container_width=True):
                    if len(st.session_state.history) > 0:
                        current_state = st.session_state.history[-1]
                        previous_target = st.session_state.target.copy()
                        new_target = st.session_state.feedback_handler.process_feedback(
                            fb_type, current_state, st.session_state.target
                        )

                        st.session_state.target["temperature"] = new_target["temperature"]
                        st.session_state.target["humidity"] = new_target["humidity"]
                        st.session_state.target["co2_max"] = new_target["co2_max"]
                        st.session_state.target["illuminance"] = new_target["illuminance"]

                        save_feedback(fb_type, previous_target, new_target, current_state)

                        temp_change = new_target["temperature"] - previous_target["temperature"]
                        if temp_change != 0:
                            st.toast(f"Целевая температура: {new_target['temperature']:.1f}°C ({temp_change:+.1f}°C)", icon="🌡️")

        temp_row2 = st.columns(2)
        for i in range(2, 4):
            label, fb_type = temp_buttons[i]
            with temp_row2[i-2]:
                if st.button(label, key=f"fb_{fb_type}", use_container_width=True):
                    if len(st.session_state.history) > 0:
                        current_state = st.session_state.history[-1]
                        previous_target = st.session_state.target.copy()
                        new_target = st.session_state.feedback_handler.process_feedback(
                            fb_type, current_state, st.session_state.target
                        )

                        st.session_state.target["temperature"] = new_target["temperature"]
                        st.session_state.target["humidity"] = new_target["humidity"]
                        st.session_state.target["co2_max"] = new_target["co2_max"]
                        st.session_state.target["illuminance"] = new_target["illuminance"]

                        save_feedback(fb_type, previous_target, new_target, current_state)

                        temp_change = new_target["temperature"] - previous_target["temperature"]
                        if temp_change != 0:
                            st.toast(f"Целевая температура: {new_target['temperature']:.1f}°C ({temp_change:+.1f}°C)", icon="🌡️")

        st.markdown("")
        st.markdown("**Влажность и воздух**")
        air_cols = st.columns(3)
        air_buttons = [
            ("Душно", "stuffy"),
            ("Сухо", "dry"),
            ("Влажно", "humid"),
        ]
        for i, (label, fb_type) in enumerate(air_buttons):
            with air_cols[i]:
                if st.button(label, key=f"fb_{fb_type}", use_container_width=True):
                    if len(st.session_state.history) > 0:
                        current_state = st.session_state.history[-1]
                        previous_target = st.session_state.target.copy()
                        new_target = st.session_state.feedback_handler.process_feedback(
                            fb_type, current_state, st.session_state.target
                        )

                        st.session_state.target["temperature"] = new_target["temperature"]
                        st.session_state.target["humidity"] = new_target["humidity"]
                        st.session_state.target["co2_max"] = new_target["co2_max"]
                        st.session_state.target["illuminance"] = new_target["illuminance"]

                        save_feedback(fb_type, previous_target, new_target, current_state)

                        if fb_type == "stuffy":
                            co2_change = new_target["co2_max"] - previous_target["co2_max"]
                            st.toast(f"Целевой CO2: {new_target['co2_max']} ppm ({co2_change:+d} ppm)", icon="💨")
                        else:
                            hum_change = new_target["humidity"] - previous_target["humidity"]
                            st.toast(f"Целевая влажность: {new_target['humidity']:.0f}% ({hum_change:+.0f}%)", icon="💧")

        summary = st.session_state.feedback_handler.get_feedback_summary()
        if summary.get("total_feedbacks", 0) > 0:
            st.caption(f"Всего фидбеков: {summary['total_feedbacks']}")

        st.markdown("---")

        st.subheader("Внешние параметры")

        if len(st.session_state.history) > 0:
            last = st.session_state.history[-1]
            st.metric("Уличная температура", f"{last.get('outdoor_temperature', 0):.1f} C")
            st.metric("Уличная влажность", f"{last.get('outdoor_humidity', 0):.1f}%")
            st.metric("Людей в помещении", f"{last.get('occupants', 0)}")
        else:
            st.info("Ожидание данных...")

        st.markdown("---")

        st.subheader("Управление устройствами")

        if "auto_control_enabled" not in st.session_state:
            st.session_state.auto_control_enabled = False

        auto_control = st.toggle(
            "Автоуправление",
            value=st.session_state.auto_control_enabled,
            key="auto_control_toggle",
            help="Устройства автоматически включаются/выключаются для поддержания целевых параметров"
        )
        st.session_state.auto_control_enabled = auto_control

        device_status = st.session_state.device_controller.get_all_status()

        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown("**Кондиционер**")
        with col2:
            ac_status = "ВКЛ" if device_status["ac"]["intensity"] > 0 else "ВЫКЛ"
            st.markdown(f"<div style='text-align: right; font-size: 0.9em;'>{ac_status} ({device_status['ac']['intensity']:.0%})</div>", unsafe_allow_html=True)
        ac_intensity = st.slider(
            "Мощность",
            0.0, 1.0,
            device_status["ac"]["intensity"],
            0.05,
            key="ac_power",
            label_visibility="collapsed"
        )
        st.session_state.device_controller.ac.manual_control(ac_intensity > 0, ac_intensity)

        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown("**Радиатор**")
        with col2:
            rad_status = "ВКЛ" if device_status["radiator"]["intensity"] > 0 else "ВЫКЛ"
            st.markdown(f"<div style='text-align: right; font-size: 0.9em;'>{rad_status} ({device_status['radiator']['intensity']:.0%})</div>", unsafe_allow_html=True)
        rad_intensity = st.slider(
            "Мощность",
            0.0, 1.0,
            device_status["radiator"]["intensity"],
            0.05,
            key="rad_power",
            label_visibility="collapsed"
        )
        st.session_state.device_controller.radiator.manual_control(rad_intensity > 0, rad_intensity)

        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown("**Увлажнитель**")
        with col2:
            hum_status = "ВКЛ" if device_status["humidifier"]["intensity"] > 0 else "ВЫКЛ"
            st.markdown(f"<div style='text-align: right; font-size: 0.9em;'>{hum_status} ({device_status['humidifier']['intensity']:.0%})</div>", unsafe_allow_html=True)
        hum_intensity = st.slider(
            "Мощность",
            0.0, 1.0,
            device_status["humidifier"]["intensity"],
            0.05,
            key="hum_power",
            label_visibility="collapsed"
        )
        st.session_state.device_controller.humidifier.manual_control(hum_intensity > 0, hum_intensity)

        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown("**Осушитель**")
        with col2:
            dehum_status = "ВКЛ" if device_status["dehumidifier"]["intensity"] > 0 else "ВЫКЛ"
            st.markdown(f"<div style='text-align: right; font-size: 0.9em;'>{dehum_status} ({device_status['dehumidifier']['intensity']:.0%})</div>", unsafe_allow_html=True)
        dehum_intensity = st.slider(
            "Мощность",
            0.0, 1.0,
            device_status["dehumidifier"]["intensity"],
            0.05,
            key="dehum_power",
            label_visibility="collapsed"
        )
        st.session_state.device_controller.dehumidifier.manual_control(dehum_intensity > 0, dehum_intensity)

        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown("**Бризер**")
        with col2:
            br_status = "ВКЛ" if device_status["breather"]["intensity"] > 0 else "ВЫКЛ"
            st.markdown(f"<div style='text-align: right; font-size: 0.9em;'>{br_status} ({device_status['breather']['intensity']:.0%})</div>", unsafe_allow_html=True)
        br_intensity = st.slider(
            "Мощность",
            0.0, 1.0,
            device_status["breather"]["intensity"],
            0.05,
            key="br_power",
            label_visibility="collapsed"
        )
        st.session_state.device_controller.breather.manual_control(br_intensity > 0, br_intensity)

        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown("**Шторы**")
        with col2:
            bl_status = "Закрыты" if device_status["blinds"]["intensity"] > 0 else "ВЫКЛ"
            st.markdown(f"<div style='text-align: right; font-size: 0.9em;'>{bl_status} ({device_status['blinds']['intensity']:.0%})</div>", unsafe_allow_html=True)
        bl_intensity = st.slider(
            "Закрытие",
            0.0, 1.0,
            device_status["blinds"]["intensity"],
            0.05,
            key="bl_power",
            label_visibility="collapsed"
        )
        st.session_state.device_controller.blinds.manual_control(bl_intensity > 0, bl_intensity)

    if st.session_state.simulation_running:
        simulation_step()
        time.sleep(1 / st.session_state.simulation_speed)
        st.rerun()


if __name__ == "__main__":
    main()
