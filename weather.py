import json
import os
import requests

FUNC_RESPONSE = {'statusCode': 200, 'body': ''}
TELEGRAM_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}'
YS_API_KEY = os.environ.get('YS_API_KEY')
OW_API_KEY = os.environ.get('OW_API_KEY')
DD_API_KEY = os.environ.get('DD_API_KEY')
DD_SEC_KEY = os.environ.get('DD_SEC_KEY')

MAX_VOICE_DURATION = 30

def send_message(text, message):
    """Отправка сообщения пользователю Telegram."""
    message_id = message['message_id']
    chat_id = message['chat']['id']
    reply_message = {'chat_id': chat_id, 'reply_to_message_id': message_id}
    
    if isinstance(text, str):
        reply_message['text'] = text
        requests.post(url=f'{TELEGRAM_API_URL}/sendMessage', json=reply_message)
    elif isinstance(text, dict):
        reply_message['voice'] = text
        requests.post(url=f'{TELEGRAM_API_URL}/sendVoice', json=reply_message)


def handler(event, context):
    """Обработчик облачной функции."""
    if TELEGRAM_BOT_TOKEN is None:
        return FUNC_RESPONSE
    if OW_API_KEY is None:
        return FUNC_RESPONSE

    update = json.loads(event['body'])

    if 'message' not in update:
        return FUNC_RESPONSE
    message_in = update['message']

    if 'location' in message_in:
        echo_text = process_location_message(message_in['location'])
    elif 'text' in message_in:
        if message_in['text'] == '/start':
            echo_text = 'Введите адрес текстовым сообщением, голосовым сообщением или отправьте свою геолокацию,' \
                        ' чтобы получить информацию о погоде'
            send_message(echo_text, message_in)
            return FUNC_RESPONSE
        if DD_API_KEY is None or DD_SEC_KEY is None:
            return FUNC_RESPONSE
        address = message_in["text"].encode('utf-8').decode('utf-8')
        echo_text = get_echo_text(address)
    elif 'voice' in message_in:
        if YS_API_KEY is None:
            return FUNC_RESPONSE
        voice_duration = message_in['voice']['duration']
        
        if voice_duration <= MAX_VOICE_DURATION:
            echo_text = process_voice_message(message_in)
        else:
            echo_text = 'Я не могу понять голосовое сообщение длительностью более 30 секунд.'
    else:
        echo_text = 'Я не могу ответить на такой тип сообщения.\n\nНо могу ответить на:\n- Текстовое сообщение ' \
                    'с названием населенного пункта.\n- Голосовое сообщение с названием населенного пункта.\n' \
                    '- Сообщение с точкой на карте.'
    
    send_message(echo_text, message_in)
    return FUNC_RESPONSE


def get_echo_text(address):
    """Из строки адреса получает сообщение, которое отправится пользователю"""
    lat, lon = get_coords_from_address(address)
    if lat and lon:
        echo_text = get_weather_info(lat, lon)
    else:
        echo_text = f'Я не нашел населенный пункт "{address}".'
    return echo_text


def get_coords_from_address(address):
    """Получает координаты (долготу и широту) из адреса."""
    r_address = requests.post(url="https://cleaner.dadata.ru/api/v1/clean/address",
                              headers={"Authorization": f"Token {DD_API_KEY}", "X-Secret": DD_SEC_KEY},
                              json=[address])
    if r_address.ok:
        result = r_address.json()[0]
        if result['qc'] == 0:
            return result['geo_lat'], result['geo_lon']
    return None, None


def get_weather_info(lat, lon):
    """Выдает информацию о погоде по координатам."""
    r = requests.get(url="https://api.openweathermap.org/data/2.5/weather",
                     params={'lat': lat, "lon": lon, 'appid': OW_API_KEY, 'units': 'metric', "lang": 'ru'})
    info_weather = r.json()
    
    weather_description = info_weather['weather'][0]['description']
    temperature = round(info_weather['main']['temp'])
    feels_like = round(info_weather['main']['feels_like'])
    pressure = round(info_weather['main']['pressure'] / 1.333)  # convert hPa to mmHg
    humidity = round(info_weather['main']['humidity'])
    visibility = info_weather.get('visibility', 'нет данных')
    wind_speed = info_weather['wind']['speed']
    wind_direction = get_wind_direction(info_weather['wind']['deg'])
    sunrise = get_time_from_timestamp(info_weather['sys']['sunrise'])
    sunset = get_time_from_timestamp(info_weather['sys']['sunset'])

    echo_text = f"{weather_description}.\nТемпература {temperature} ℃, ощущается как {feels_like} ℃.\n" \
                f"Атмосферное давление {pressure} мм рт. ст.\nВлажность {humidity}%.\n" \
                f"Видимость {visibility} метров.\nВетер {wind_speed} м/с {wind_direction}.\n" \
                f"Восход солнца {sunrise} МСК. Закат {sunset} МСК."
    
    return echo_text


def process_location_message(location):
    """Обработка сообщения с координатами"""
    lat = location['latitude']
    lon = location['longitude']
    return get_weather_info(lat, lon)


def process_voice_message(message):
    """Обработка голосового сообщения"""
    # Ищем путь аудио файла
    r_file = requests.get(url=f'{TELEGRAM_API_URL}/getFile', params={'file_id': message['voice']['file_id']})
    file_path = r_file.json()['result']['file_path']
    # Скачиваем файл из телеграмма
    r_file_download = requests.get(url=f'https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}')
    audio_file = r_file_download.content
    # Отправляем запрос YC SpeechKit
    r_stt = requests.post(url='https://stt.api.cloud.yandex.net/speech/v1/stt:recognize',
                          headers={"Authorization": f"Api-Key {YS_API_KEY}"},
                          data=audio_file)
    
    if r_stt.ok:
        address = r_stt.json()['result']
        return get_echo_text(address)
    else:
        return 'Не удалось распознать голосовое сообщение.'


def get_wind_direction(degrees):
    """Получение направления ветра по градусам"""
    directions = ['С', 'СВ', 'В', 'ЮВ', 'Ю', 'ЮЗ', 'З', 'СЗ']
    index = round(degrees / 45) % 8
    return directions[index]


def get_time_from_timestamp(timestamp):
    """Преобразование времени из timestamp в формат HH:MM"""
    from datetime import datetime
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%H:%M")
