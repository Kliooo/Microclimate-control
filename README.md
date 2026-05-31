# Microclimate Control Simulator

Modeling and simulation of an automatic indoor microclimate control system (temperature, humidity, CO₂, illuminance, noise).

## Architecture

```
src/
├── physics_model.py      — room physics model (heat balance, CO₂, moisture)
├── sensor_generator.py   — sensor readings generator (noise, outliers)
├── devices.py            — actuator simulation (AC, breather, humidifier, etc.)
├── central_hub.py        — data normalization, PMV/IEQ calculation, safety checks
├── feedback_system.py    — user feedback handling and adaptive learning
├── ai_reporter.py        — AI analysis via OpenRouter and Telegram delivery
├── weather_api.py        — real weather data fetching
├── app.py                — Streamlit UI
└── constants.py          — GOST standards and target parameters

configs/
└── room_config.yaml      — room configuration (geometry, climate, devices)

documentation/
└── Отчёт.docx            — research report (in Russian)
```

## Installation

```bash
pip install -r requirements.txt
```

## API Keys

Create a `.env` file in the project root (see `.env.example`):

```
OPENROUTER_API_KEY=sk-or-v1-...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

- **OpenRouter key** — get one at https://openrouter.ai/keys (required for AI analysis).
- **Telegram token** — create a bot via [@BotFather](https://t.me/BotFather) on Telegram and copy the token.
- **Telegram chat ID** — send a message to your bot, then visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` to find your chat ID.

## Running

```bash
streamlit run src/app.py
```

## Configuration

Room parameters (geometry, season, device specs) are set in `configs/room_config.yaml`.
