from datetime import datetime
import requests
import npyscreen
import configparser
import os

# Класс, предоставляющий функциональность для получения прогноза погоды
class WeatherService:
    def __init__(self):
        # Заголовки для доступа к API
        self.headers = {
            "X-RapidAPI-Key": "24466752d4msh6f48b6cd9aa407dp1e01dajsn6208b431c57d",
            "X-RapidAPI-Host": "ai-weather-by-meteosource.p.rapidapi.com"
        }
        # Типы ошибок и соответствующие сообщения
        self.error_message_types = {1: "Ошибка подключения", 2: "Ошибка запроса"}
        # Статус выполнения последнего запроса
        self.request_status = False

    # Обработчик ошибок при выполнении запроса
    def error_handler(self, response):
        if response.status_code == 200:
            return "ОК"
        elif response.status_code == 429:
            return "Слишком много запросов (429)"
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
        url = "https://ai-weather-by-meteosource.p.rapidapi.com/hourly"
        querystring = {"place_id": location}
        try:
            response = requests.get(url, headers=self.headers, params=querystring)
            response.raise_for_status()
            data = response.json()
            # Получаем текущее время
            now = datetime.now()
            current_hour = now.hour
            # Вычисляем разницу в часах между текущим временем и запрашиваемым временем
            hour_difference = (hour - current_hour) % 24
            if hour_difference < 0:
                hour_difference += 24
            # Если выбран час, который уже прошел сегодня, то переходим к завтрашнему дню
            if hour < current_hour:
                day = 0  # 1 для завтрашнего дня
            # Пересчитываем индекс
            index = hour_difference + 24 * day
            # Получаем данные для выбранного часа
            index = int(index)
            selected_hour_data = data['hourly']['data'][index]
            # Создаем словарь с данными о погоде
            weather_data = {
                'weather': selected_hour_data['weather'],
                'temperature': selected_hour_data['temperature'],
                'feels_like': selected_hour_data['feels_like'],
                'wind_chill': selected_hour_data['wind_chill'],
                'dew_point': selected_hour_data['dew_point'],
                'pressure': selected_hour_data['pressure'],
                'ozone': selected_hour_data['ozone'],
                'uv_index': selected_hour_data['uv_index'],
                'humidity': selected_hour_data['humidity'],
                'visibility': selected_hour_data['visibility'],
                'probability_precipitation': selected_hour_data['probability']['precipitation'],
                'precipitation_type': selected_hour_data['precipitation']['type'],
            }
            self.request_status = True
            return weather_data
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
        last_date_time = config.get('RequestCount', 'last_date_time', fallback='')
        return request_count, last_date_time

    # Метод для обновления счетчика запросов в конфигурационном файле
    def update_request_count(self, date_time):
        config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
        config = configparser.ConfigParser()
        config.read(config_path)
        request_count, last_date_time = self.load_request_count()
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
        max_requests_per_month = 100  # Максимальное количество запросов в месяц
        request_count, _ = self.load_request_count()
        remaining_requests = max_requests_per_month - request_count
        # Если секции RequestCount нет, добавляем ее
        if not config.has_section('RequestCount'):
            config.add_section('RequestCount')
        # Обновляем значение remaining_requests
        config.set('RequestCount', 'remaining_requests', str(remaining_requests))
        # Записываем обновленные данные обратно в файл
        with open(config_path, 'w') as configfile:
            config.write(configfile)
        return remaining_requests


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
        status, error_message, remaining_requests = self.weather_service.request_status, "", 100
        if isinstance(self.weather_service.request_status, bool) and not self.weather_service.request_status:
            error_message = self.weather_service.error_handler(self.today_forecast)
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
        forecast_data = self.weather_service.request_forecast(self.location, self.selected_time, self.selected_day)
        if self.selected_day == 0:
            self.today_forecast = forecast_data
        elif self.selected_day == 1:
            self.tomorrow_forecast = forecast_data
        return forecast_data

    # Метод для возврата статуса запроса
    def return_request_status(self):
        status, error_message, remaining_requests, request_count = self.get_request_status()
        self.request_status_relay = f"Status: {'OK' if status else 'Error'}"
        self.error_message_relay = f"Error: {error_message}"
        return self.request_status_relay, self.error_message_relay, remaining_requests, request_count


# Класс, представляющий пользовательский интерфейс на основе библиотеки npyscreen
class NpyscreenInterface(npyscreen.NPSAppManaged):
    # Класс для главной формы приложения
    class MainForm(npyscreen.ActionFormV2):
        # Метод создания виджетов и настройки формы
        def create(self):
            # Виджет для ввода города
            self.city_widget = self.add(npyscreen.TitleText, name="Город:", rely=1, relx=1)
            # Виджет для выбора времени с помощью слайдера
            self.time_widget = self.add(npyscreen.TitleSlider, out_of=23, step=1, name="Выберите час:", rely=4, relx=1)
            # Виджет для выбора дня с помощью списка
            self.day_widget = self.add(npyscreen.TitleSelectOne, max_height=2, value=[0], name="День:", values=["Сегодня", "Завтра"], rely=6, relx=1)
            # Инициализация переменных для отображения статуса запроса, ошибки и данных о погоде
            self.request_count = 0
            self.status_widget = self.add(npyscreen.TitleFixedText, name="Статус запроса:", rely=8, relx=1)
            self.error_widget = self.add(npyscreen.MultiLineEdit, value="", name="Ошибка:", rely=10, relx=1)
            self.weather_widget = self.add(npyscreen.MultiLineEdit, value="", name="Погода:", rely=12, relx=1, max_height=13, max_width=48)

        # Метод для форматирования данных о погоде
        def format_weather_data(self, weather_data):
            formatted_data = []
            for key, value in weather_data.items():
                formatted_data.append(f"{key}: {value}")
            return '\n'.join(formatted_data)

        # Обработчик события "ОК"
        def on_ok(self):
            try:
                # Вызываем метод on_ok родительского приложения
                self.parentApp.on_ok()
                # Получаем прогноз погоды с использованием объекта WeatherApp
                forecast_data = self.parentApp.weather_app.request_forecast_data()
                if isinstance(forecast_data, requests.Response):
                    # Обработка ошибок запроса и отображение сообщения об ошибке
                    error_message = self.parentApp.weather_app.weather_service.error_handler(forecast_data)
                    self.parentApp.getForm("MAIN").error_widget.value = f"Ошибка запроса: {error_message}"
                    self.parentApp.getForm("MAIN").error_widget.display()
                    return
                # Форматируем данные и отображаем их в виджете погоды
                formatted_data = self.format_weather_data(forecast_data)
                self.weather_widget.value = formatted_data
                self.forecast_data = formatted_data
                self.parentApp.getForm("MAIN").weather_widget.value = formatted_data
                # Обновление виджета погоды
                self.parentApp.getForm("MAIN").weather_widget.display()
            except requests.RequestException as e:
                # Обработка ошибок запроса и отображение сообщения об ошибке
                error_message = self.parentApp.weather_app.weather_service.error_handler(e)
                self.parentApp.getForm("MAIN").error_widget.value = f"Ошибка запроса: {error_message}"
                self.parentApp.getForm("MAIN").error_widget.display()

        # Обработчик события "Отмена"
        def on_cancel(self):
            # Закрываем форму
            self.parentApp.setNextForm(None)
            self.editing = False

    # Метод, выполняющийся при запуске приложения
    def onStart(self):
        # Создаем объект WeatherApp
        self.weather_app = WeatherApp(WeatherService())
        # Устанавливаем начальные значения для дня и времени прогноза
        self.weather_app.set_day(0)
        self.weather_app.set_forecast_time(12)
        # Добавляем главную форму в приложение
        self.addForm("MAIN", self.MainForm)
        # Получаем и отображаем текущее количество оставшихся запросов
        remaining_requests = self.weather_app.weather_service.remain_request_number()

    # Обработчик события "ОК"
    def on_ok(self):
        # Получаем значения из виджетов главной формы
        city = self.getForm("MAIN").city_widget.value
        time = self.getForm("MAIN").time_widget.value
        day = self.getForm("MAIN").day_widget.value[0]
        if not city.isalpha() or not city.isascii():
            print("Название населенного пункта должно содержать только латинские буквы. Пожалуйста, введите корректное название.")
            # Очистка строки ввода
            self.getForm("MAIN").city_widget.value = ""
            return
        # Устанавливаем выбранный день в объекте WeatherApp
        if day == 0:
            self.weather_app.set_day(0)
        elif day == 1:
            self.weather_app.set_day(1)
        # Устанавливаем время и местоположение в объекте WeatherApp
        self.weather_app.set_forecast_time(time)
        self.weather_app.set_location(city)
        # Получаем прогноз погоды и информацию о статусе запроса
        forecast_data = self.weather_app.request_forecast_data()
        status, error_message, remaining_requests, request_count = self.weather_app.return_request_status()
        # Обновляем счетчик запросов в конфигурационном файле
        if status:
            date_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.weather_app.weather_service.update_request_count(date_time)
        # Отображаем информацию о статусе, ошибке и оставшихся запросах
        remaining_requests = self.weather_app.weather_service.remain_request_number()
        self.getForm("MAIN").status_widget.value = status
        self.getForm("MAIN").error_widget.value = f"Осталось запросов в месяц: {remaining_requests}\n"
        # Обновление виджетов
        self.getForm("MAIN").status_widget.display()
        self.getForm("MAIN").error_widget.display()
        self.getForm("MAIN").display()

# Запуск приложения при выполнении скрипта
if __name__ == "__main__":
    app = NpyscreenInterface()
    app.run()
