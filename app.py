import aiohttp
import asyncio
from datetime import datetime
import requests
import npyscreen
import configparser
import os
import curses
import json
import multiprocessing
import time


# Класс, предоставляющий функциональность для получения прогноза погоды
class WeatherService:
    def __init__(self):
        # Заголовки для доступа к API
        self.headers = {
            "X-RapidAPI-Key": "675c699c85msh3d8739c0751cb75p1b3e52jsn54762decb74b",
            "X-RapidAPI-Host": 'ai-weather-by-meteosource.p.rapidapi.com'
        }
        # Типы ошибок и соответствующие сообщения
        self.error_message_types = {
            1: "Ошибка подключения",
            2: "Ошибка запроса"
        }
        # Статус выполнения последнего запроса
        self.request_status = False
        self.queue_lock = multiprocessing.Lock()

    async def request_forecast(self, location, querystring, headers):
        url = "ai-weather-by-meteosource.p.rapidapi.com"
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=querystring, headers=headers
            ) as response:
                result = await response.json()
                return result

    def _worker_process(self, location, querystring, headers):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                self.request_forecast(location, querystring, headers)
            )
            # Используем мьютекс для синхронизации доступа к очереди
            with self.queue_lock:
                self.result_queue.put(result)
        except Exception as e:
            # Используем мьютекс для синхронизации доступа к очереди
            with self.queue_lock:
                self.result_queue.put(e)

    def request_forecast_multiprocess(self, location, querystring, headers):
        process = multiprocessing.Process(
            target=self._worker_process,
            args=(location, querystring, headers)
        )
        process.start()
        start_time = time.time()
        while process.is_alive():
            process.join(timeout=1)
            elapsed_time = time.time() - start_time
            if elapsed_time > 60:
                # Используем мьютекс для синхронизации доступа к очереди
                with self.queue_lock:
                    process.terminate()
                    process.join()
                    self.result_queue.put("Процесс завершён из-за простоя.")
                break
        # Дожидаемся, когда результат будет добавлен в очередь
        while True:
            with self.queue_lock:
                if not self.result_queue.empty():
                    result = self.result_queue.get()
                    break
        return result

    # Обработчик ошибок при выполнении запроса
    def error_handler(self, response):
        # Проверяем, является ли response словарем
        if isinstance(response, dict):
            if 'temperature' in response and 'weather' in response:
                return "Данные взяты из кэша"
        elif isinstance(
            response, requests.Response
        ) and response.status_code == 200:
            return "ОК"
        elif response.status_code == 429:
            return "Превышен лимит запросов (429)"
        elif response.status_code == 403:
            return "Доступ к API заблокирован (403)"
        elif response.status_code == 404:
            return "Ресурс не найден (404)"
        elif response.status_code == 500:
            return "Внутренняя ошибка сервера (500)"
        elif response.status_code == 503:
            return "Сервис временно недоступен (503)"
        elif isinstance(response, requests.ConnectionError):
            return "Ошибка подключения к Интернету"
        else:
            return f"Неизвестная ошибка: {response.status_code}"

    # Метод для выполнения запроса на получение прогноза погоды
    def request_forecast(self, location, hour, day=0):
        cached_data = self.load_forecast_from_file(location, day, hour)
        if cached_data:
            return cached_data
        else:
            url = "https://ai-weather-by-meteosource.p.rapidapi.com/hourly"
            querystring = {"place_id": location}
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    params=querystring
                )
                response.raise_for_status()
                data = response.json()
                forecast_data = []
                # Получаем текущее время
                now = datetime.now()
                current_hour = now.hour
                # Вычисляем разницу в часах
                # между текущим временем и запрашиваемым временем
                hour_difference = (int(hour) - current_hour) % 24
                if hour_difference < 0:
                    hour_difference += 24
                # Если выбран час, который уже прошел сегодня,
                # то переходим к завтрашнему дню
                if int(hour) < current_hour:
                    day = 0  # 1 для завтрашнего дня
                # Пересчитываем индекс
                index = hour_difference + 24 * day
                # Получаем данные для выбранного часа
                index = int(index)
                selected_hour_data = data['hourly']['data'][index]
                # Создаем словарь с данными о погоде
                forecast_data = {
                    'Погода': selected_hour_data['weather'],
                    'Температура (ощущается как)': f"{selected_hour_data['temperature']} ({selected_hour_data['feels_like']})",
                    'Ощущается как': selected_hour_data['feels_like'],
                    'Точка росы': selected_hour_data['dew_point'],
                    'Давление': selected_hour_data['pressure'],
                    'ozone': selected_hour_data['ozone'],
                    'УФ-индекс': selected_hour_data['uv_index'],
                    'Влажность': selected_hour_data['humidity'],
                    'Видимость': selected_hour_data['visibility'],
                    'Вероятность выпадения осадков': selected_hour_data['probability']['precipitation'],
                    'Тип осадков': selected_hour_data['precipitation']['type'],
                    'Скорость ветра': selected_hour_data['wind']['speed'],
                    'Порывы ветра': selected_hour_data['wind']['gusts'],
                    'Направление ветра': selected_hour_data['wind']['dir'],
                    'Угол ветра': selected_hour_data['wind']['angle'],
                    'Ветро-холодовой индекс': selected_hour_data['wind_chill']
                }
                self.request_status = True
                if self.request_status:
                    self.save_forecast_to_file(
                        location, day, hour, forecast_data
                    )
                return forecast_data
            except requests.RequestException as e:
                self.request_status = False
                return response

    # Метод для загрузки счетчика запросов из конфигурационного файла
    def load_request_count(self):
        config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
        config = configparser.ConfigParser()
        # Если файл config.ini не существует, создаем его
        if not os.path.exists(config_path):
            config.add_section('RequestCount')
            config.set('RequestCount', 'count', '0')
            config.set('RequestCount', 'last_date_time', '')
            with open(config_path, 'w') as configfile:
                config.write(configfile)
        config.read(config_path)
        request_count = config.getint('RequestCount', 'count', fallback=0)
        last_date_time = config.get(
            'RequestCount',
            'last_date_time',
            fallback=''
        )
        return request_count, last_date_time

    # Метод для обновления счетчика запросов в конфигурационном файле
    def update_request_count(self, date_time, is_successful_request=True):
        config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
        config = configparser.ConfigParser()
        config.read(config_path)
        request_count, last_date_time = self.load_request_count()

        if is_successful_request:
            # Увеличиваем счетчик только для успешных запросов
            request_count += 1

        self.request_count = request_count  # обновляем значение в объекте
        # Если секции RequestCount нет, добавляем ее
        if not config.has_section('RequestCount'):
            config.add_section('RequestCount')
        # Обновляем значения count и last_date_time
        config.set('RequestCount', 'count', str(request_count))
        config.set('RequestCount', 'last_date_time', date_time)
        # Записываем обновленные данные обратно в файл
        with open(config_path, 'w') as configfile:
            config.write(configfile)

    # Метод для получения оставшегося числа запросов
    def remain_request_number(self):
        config_path = os.path.join(os.path.dirname(__file__), 'config.ini')

        config = configparser.ConfigParser()
        config.read(config_path)
        # Максимальное количество запросов в месяц
        max_requests_per_month = 100
        request_count, _ = self.load_request_count()
        remaining_requests = max_requests_per_month - request_count
        # Если секции RequestCount нет, добавляем ее
        if not config.has_section('RequestCount'):
            config.add_section('RequestCount')
        # Обновляем значение remaining_requests
        config.set(
            'RequestCount',
            'remaining_requests',
            str(remaining_requests)
        )
        # Записываем обновленные данные обратно в файл
        with open(config_path, 'w') as configfile:
            config.write(configfile)
        return remaining_requests

    # Метод для сохранения прогноза погоды в файл
    def save_forecast_to_file(self, location, day, hour, forecast_data):
        cache_folder = os.path.join(os.path.dirname(__file__), 'cache')
        os.makedirs(cache_folder, exist_ok=True)
        filename = f"{location}_{day}_{hour}.json"
        filepath = os.path.join(cache_folder, filename)
        with open(filepath, 'w') as file:
            json.dump(forecast_data, file)

    # Метод для загрузки прогноза погоды из файла
    def load_forecast_from_file(self, location, day, hour):
        cache_folder = os.path.join(os.path.dirname(__file__), 'cache')
        filename = f"{location}_{day}_{hour}.json"
        filepath = os.path.join(cache_folder, filename)
        if os.path.exists(filepath):
            with open(filepath, 'r') as file:
                cached_data = json.load(file)
            return cached_data
        return None


# Класс, представляющий приложение для отображения прогноза погоды
class WeatherApp:
    def __init__(self, weather_service):
        self.today_forecast = {}
        self.tomorrow_forecast = {}
        self.weather_service = weather_service
        self.location = ""
        self.selected_time = ""
        self.request_status_relay = ""
        self.error_message_relay = ""
        self.selected_day = 0

    # Метод для установки времени прогноза
    def set_forecast_time(self, hour):
        self.selected_time = hour
        self.request_forecast_data()

    # Метод для получения статуса запроса
    def get_request_status(self):
        status, error_message, remaining_requests = (
            self.weather_service.request_status,
            "",
            100
        )
        if isinstance(
            self.weather_service.request_status,
            bool
        ) and not self.weather_service.request_status:
            error_message = self.weather_service.error_handler(
                self.get_forecast_data()
            )
            remaining_requests = self.weather_service.remain_request_number()
        # Загружаем текущий счетчик запросов из конфигурационного файла
        request_count, _ = self.weather_service.load_request_count()
        return status, error_message, remaining_requests, request_count

    # Метод для установки местоположения
    def set_location(self, location):
        self.location = location
        self.request_forecast_data()

    # Метод для установки дня
    def set_day(self, day):
        self.selected_day = day
        self.request_forecast_data()

    # Метод для получения данных прогноза
    def get_forecast_data(self):
        if self.selected_day == 0:
            return self.today_forecast
        elif self.selected_day == 1:
            return self.tomorrow_forecast

    # Метод для выполнения запроса на получение прогноза
    def request_forecast_data(self):
        forecast_data = self.weather_service.request_forecast(
            self.location,
            self.selected_time,
            self.selected_day
        )
        if self.selected_day == 0:
            self.today_forecast = forecast_data
        elif self.selected_day == 1:
            self.tomorrow_forecast = forecast_data
        return forecast_data

    # Метод для возврата статуса запроса
    def return_request_status(self):
        status, error_message, remaining_requests, request_count = (
            self.get_request_status()
        )
        self.request_status_relay = f"Status: {'OK' if status else 'Error'}"
        self.error_message_relay = f"{error_message}"
        return (
            self.request_status_relay,
            self.error_message_relay,
            remaining_requests,
            request_count
        )


# Класс, представляющий пользовательский интерфейс
class NpyscreenInterface(npyscreen.NPSAppManaged):
    class MainForm(npyscreen.ActionFormV2):
        def create(self):
            # Виджет для ввода времени
            self.time_widget_box = self.add(
                npyscreen.BoxTitle,
                relx=0,
                rely=0,
                max_width=76,
                max_height=4
            )
            self.time_widget_box.name = "Время прогноза"
            text_widget_time = self.add(
                npyscreen.Textfield,
                value="Выберите час:",
                max_width=35,
                relx=2,
                rely=2,
                editable=False
            )
            self.time_widget_box.entry_widget = text_widget_time

            self.time_widget = self.add(
                npyscreen.Textfield,
                value="00",
                max_width=35,
                relx=38,
                rely=2,
                editable=True
            )
            self.selected_time_field = self.time_widget
            self.selected_time_field.add_handlers(
                {
                    curses.KEY_LEFT: self.move_hour_left,
                    curses.KEY_RIGHT: self.move_hour_right
                }
            )

            # Виджет "Запросы"
            self.remaining_requests_box = self.add(
                npyscreen.BoxTitle,
                relx=76, rely=0,
                max_width=41,
                max_height=4
            )
            self.remaining_requests_box.name = "Запросы"
            text_widget = self.add(
                npyscreen.Textfield,
                value="Количество оставшихся запросов: ",
                rely=2,
                relx=78,
                editable=False
            )
            self.remaining_requests_box.entry_widget = text_widget

            # Виджет для ввода дня
            self.day_widget_box = self.add(
                npyscreen.BoxBasic,
                rely=4,
                relx=0,
                max_width=35,
                max_height=8,
                editable=False
            )
            self.day_widget = self.add(
                npyscreen.TitleSelectOne,
                max_height=2,
                max_width=30,
                value=[0],
                name="День:",
                values=["Сегодня", "Завтра"],
                rely=6,
                relx=2,
                scroll_exit=True
            )

            # Виджет для ввода города
            self.city_widget_box = self.add(
                npyscreen.BoxTitle,
                name="Город:",
                rely=4,
                relx=36,
                max_width=80,
                max_height=4
            )
            self.city_widget = self.add(
                npyscreen.Textfield,
                rely=6,
                relx=38,
                max_width=40,
                max_height=4
            )
            self.city_widget.add_handlers(
                {curses.ascii.NL: self.on_enter_button_pressed_city_widget}
            )
            self.city_widget_box.entry_widget = self.city_widget

            # Виджет для отображения данных о погоде
            self.weather_widget_box = self.add(
                npyscreen.BoxBasic,
                rely=8,
                relx=36,
                max_width=80,
                max_height=20
            )
            self.weather_widget = self.add(
                npyscreen.MultiLineEdit,
                value="",
                rely=9,
                relx=37,
                max_width=76,
                max_height=16
            )

            # Инициализация переменных
            # для отображения статуса запроса, ошибки и данных о погоде
            self.request_count = 0
            self.status_widget_box = self.add(
                npyscreen.BoxBasic,
                name="Статус запроса:",
                rely=12,
                relx=0,
                max_width=35,
                max_height=8
            )
            self.status_widget = self.add(
                npyscreen.BoxBasic,
                name="Статус запроса:",
                rely=12,
                relx=0,
                max_width=35,
                max_height=8
            )
            self.error_widget_box = self.add(
                npyscreen.BoxBasic,
                value="",
                name="Ошибка:",
                rely=20,
                relx=0,
                max_width=35,
                max_height=8
            )
            self.error_widget = self.add(
                npyscreen.MultiLineEdit,
                value="",
                rely=21,
                relx=1,
                max_width=33,
                max_height=6
            )

        def on_enter_button_pressed_city_widget(self, button_pressed):
            """Обработчик нажатия Enter в виджете ввода города."""
            if button_pressed == curses.ascii.NL:
                self.city_widget.editable = False
                self.editing = self.on_ok

        def on_enter_button_pressed_time_widget(self, *args, **kwargs):
            self.editing = self.day_widget

        def on_enter_button_pressed_day_widget(self, *args, **kwargs):
            self.editing = self.city_widget

        def on_up_button_pressed_day_widget(self, button_pressed):
            """Перемещение часов влево."""
            if button_pressed == curses.KEY_UP:
                self.editing = False
                self.day_widget.editable = False
                self.day_widget.display()
                self.time_widget.editable = True
                self.time_widget.edit()

        def move_hour_left(self, key):
            """Перемещение часов влево."""
            current_time = self.selected_time_field.value
            if current_time and len(current_time) >= 2:
                hour = int(current_time)
                hour -= 1
                if hour < 0:
                    hour = 23
                updated_time = f"{hour:02d}"
                self.selected_time_field.value = updated_time
                self.selected_time_field.display()

        def move_hour_right(self, key):
            """Перемещение часов вправо."""
            current_time = self.selected_time_field.value
            if current_time and len(current_time) >= 2:
                hour = int(current_time)
                hour += 1
                if hour > 23:
                    hour = 0
                updated_time = f"{hour:02d}"
                self.selected_time_field.value = updated_time
                self.selected_time_field.display()

        # Метод для форматирования данных о погоде
        def format_weather_data(self, weather_data):
            """Форматирование данных о погоде для отображения."""
            formatted_data = []
            half_len = len(weather_data) // 2 + len(weather_data) % 2
            for i, (key, value) in enumerate(weather_data.items()):
                if i == half_len:
                    formatted_data.append(' ' * 20)
                formatted_data.append(f"{key}: {value:<15}")
            return '\n'.join(formatted_data)

        def on_ok(self):
            """Обработчик события нажатия кнопки 'ОК'."""
            try:
                self.parentApp.on_ok()
                cached_data = (
                    self.parentApp.weather_app.weather_service.load_forecast_from_file(
                        self.parentApp.weather_app.location,
                        self.parentApp.weather_app.selected_day,
                        self.parentApp.weather_app.selected_time
                    )
                )
                if cached_data:
                    formatted_data = self.parentApp.getForm(
                        "MAIN"
                    ).format_weather_data(
                        cached_data
                    )
                    self.parentApp.getForm("MAIN").weather_widget.values = (
                        formatted_data.splitlines()
                    )
                    self.parentApp.getForm("MAIN").weather_widget.value = (
                        formatted_data
                    )
                    date_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    self.parentApp.weather_app.weather_service.update_request_count(
                        date_time,
                        is_successful_request=False
                    )
                    error_message = (
                        self.parentApp.weather_app.weather_service.error_handler(
                            cached_data
                        )
                    )
                    self.parentApp.getForm("MAIN").error_widget.value = (
                        f"Ошибка: {error_message}"
                    )
                    self.parentApp.getForm("MAIN").error_widget.display()
                    self.parentApp.getForm("MAIN").weather_widget.display()
                    self.parentApp.getForm("MAIN").display()
                    return cached_data
                else:
                    forecast_data = (
                        self.parentApp.weather_app.request_forecast_data()
                    )

                    if isinstance(forecast_data, requests.Response):
                        error_message = (
                            self.parentApp.weather_app.weather_service.error_handler(
                                forecast_data
                            )
                        )
                        self.parentApp.getForm("MAIN").error_widget.value = (
                            f"{error_message}"
                        )
                        return
                    formatted_data = (
                        self.parentApp.getForm("MAIN").format_weather_data(
                            forecast_data
                        )
                    )
                    self.parentApp.getForm("MAIN").weather_widget.values = (
                        formatted_data.splitlines()
                    )
                    self.parentApp.getForm("MAIN").weather_widget.value = (
                        formatted_data
                    )
                    date_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    self.parentApp.weather_app.weather_service.update_request_count(
                        date_time
                    )
                    remaining_requests = (
                        self.parentApp.weather_app.weather_service.remain_request_number()
                    )
                    self.parentApp.getForm("MAIN").remaining_requests_box.values = (
                        f"Осталось запросов в месяц: {remaining_requests}"
                    )
                    status, error_message, _, _ = (
                        self.parentApp.weather_app.get_request_status()
                    )
                    self.parentApp.getForm("MAIN").status_widget.value = (
                        f"Status: {'OK' if status else 'Error'}"
                    )
            finally:
                # Вызываем display() один раз после всех изменений виджета
                self.parentApp.getForm("MAIN").display()

        def on_cancel(self):
            """Обработчик события нажатия кнопки 'Отмена'."""
            self.parentApp.setNextForm(None)
            self.editing = False

    def onStart(self):
        self.weather_app = WeatherApp(WeatherService())
        self.addForm("MAIN", self.MainForm)
        remaining_requests = (
            self.weather_app.weather_service.remain_request_number()
        )
        self.getForm("MAIN").remaining_requests_box.entry_widget.value = (
            f"Осталось запросов в месяц: {remaining_requests}\n"
        )
        self.getForm("MAIN").remaining_requests_box.entry_widget.display()
        self.getForm("MAIN").remaining_requests_box.display()

    def on_ok(self):
        time = self.getForm("MAIN").time_widget.value
        day = self.getForm("MAIN").day_widget.value[0]
        city_widget = self.getForm("MAIN").city_widget
        city = city_widget.value if city_widget else ""
        if day == 0:
            self.weather_app.set_day(0)
        elif day == 1:
            self.weather_app.set_day(1)
        self.weather_app.set_forecast_time(time)
        self.weather_app.set_location(city)
        # Теперь выполнение запроса
        # будет происходить только после нажатия кнопки "ОК"
        cached_data = self.weather_app.weather_service.load_forecast_from_file(
            self.weather_app.location,
            self.weather_app.selected_day,
            self.weather_app.selected_time
        )
        if cached_data is not None:
            forecast_data = cached_data
        else:
            forecast_data = self.weather_app.request_forecast_data()
            remaining_requests = (
                self.weather_app.weather_service.remain_request_number()
            )
            self.getForm("MAIN").remaining_requests_box.entry_widget.value = (
                f"Осталось запросов в месяц: {remaining_requests}"
            )
            self.getForm("MAIN").remaining_requests_box.entry_widget.display()
        status, error_message, remaining_requests, request_count = (
            self.weather_app.return_request_status()
        )
        if status:
            date_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.weather_app.weather_service.update_request_count(date_time)
        remaining_requests = (
            self.weather_app.weather_service.remain_request_number()
        )
        self.getForm("MAIN").status_widget.value = status
        self.getForm("MAIN").error_widget.value = f"{error_message}"
        self.getForm("MAIN").status_widget.display()
        self.getForm("MAIN").error_widget.display()
        self.getForm("MAIN").display()


if __name__ == "__main__":
    app = NpyscreenInterface()
    app.run()
