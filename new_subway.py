#!/usr/bin/env python3
"""
MTA Subway Display for RGB LED Matrix (using nyct-gtfs)
Full-featured with pixel-art icons, train circles, and scheduled on/off hours.
Includes a rotating Riddle of the Day page.
Includes Markets page (DOW + VIX) shown every 10 minutes for 1 minute.
"""

import time
import os
from datetime import datetime, date
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics
from nyct_gtfs import NYCTFeed
from PIL import Image
import threading
import requests
import random
import yfinance as yf

# ------------------- CONFIG -------------------
WALK_TIME_TO_STATIONS_MINUTES = 10
LATITUDE = 40.7128
LONGITUDE = -74.0060

STATIONS = {
    'E': {'stop_id': 'F09', 'direction': 'S', 'name': 'Court Sq'},
    '7': {'stop_id': '721', 'direction': 'S', 'name': 'Vern-Jack'}
}

ACTIVE_START_HOUR = 6
ACTIVE_END_HOUR = 23

# Markets: show for 1 minute every 10 minutes
MARKET_SHOW_DURATION_SEC = 60
MARKET_INTERVAL_MINUTES = 10
# ---------------------------------------------

# Bondi DOW page — hardcoded absolute path to image
BONDI_IMAGE_PATH = "/usr/local/share/pam-bondi-resized.png"
BONDI_SHOW_MINUTES = [5, 15, 25, 35, 45, 55]  # which minutes past the hour to show it
BONDI_SHOW_DURATION_SEC = 45                   # how long to show it

# Speech-bubble geometry (LED pixels)
BUBBLE_X, BUBBLE_Y = 32, 1
BUBBLE_W, BUBBLE_H = 31, 10

# Pixel-art icons
_ = None

SUN = [
    [_,_,_,'Y',_,_,'Y',_,_,_],
    [_,'Y',_,_,_,_,_,_,'Y',_],
    [_,_,'Y','Y','Y','Y',_,_,_,_],
    ['Y',_,'Y','Y','Y','Y',_,'Y',_,_],
    [_,_,'Y','Y','Y','Y',_,_,_,_],
    [_,_,'Y','Y','Y','Y',_,_,_,_],
    ['Y',_,'Y','Y','Y','Y',_,'Y',_,_],
    [_,_,'Y','Y','Y','Y',_,_,_,_],
    [_,'Y',_,_,_,_,_,_,'Y',_],
    [_,_,_,'Y',_,_,'Y',_,_,_],
]

CLOUD = [
    [_,_,_,_,_,_,_,_,_,_],
    [_,_,'W','W',_,_,_,_,_,_],
    [_,'W','W','W','W','W',_,_,_,_],
    ['W','W','W','W','W','W','W',_,_,_],
    ['W','W','W','W','W','W','W','W',_,_],
    ['G','G','G','G','G','G','G','G',_,_],
    [_,'G','G','G','G','G','G',_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
]

RAIN = [
    [_,_,'W','W','W','W',_,_,_,_],
    [_,'W','W','W','W','W','W',_,_,_],
    ['W','W','W','W','W','W','W','W',_,_],
    ['G','G','G','G','G','G','G','G',_,_],
    [_,'B',_,'B',_,'B',_,'B',_,_],
    [_,'B',_,'B',_,'B',_,'B',_,_],
    [_,_,'B',_,'B',_,'B',_,_,_],
    [_,_,'B',_,'B',_,'B',_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
]

SNOW = [
    [_,'W',_,_,'W',_,_,'W',_,_],
    [_,_,'W',_,'W',_,'W',_,_,_],
    [_,_,_,'W','W','W',_,_,_,_],
    ['W','W','W','W','W','W','W','W','W',_],
    [_,_,_,'W','W','W',_,_,_,_],
    [_,_,'W',_,'W',_,'W',_,_,_],
    [_,'W',_,_,'W',_,_,'W',_,_],
    [_,_,_,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
]

STORM = [
    [_,_,_,'Y','Y','Y',_,_,_,_],
    [_,_,'Y','Y','Y',_,_,_,_,_],
    [_,'Y','Y','Y',_,_,_,_,_,_],
    ['Y','Y','Y','Y','Y','Y',_,_,_,_],
    [_,_,_,'Y','Y','Y',_,_,_,_],
    [_,_,'Y','Y','Y',_,_,_,_,_],
    [_,'Y','Y','Y',_,_,_,_,_,_],
    ['Y','Y',_,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
]

FOG = [
    [_,_,_,_,_,_,_,_,_,_],
    ['G','G','G','G','G','G','G','G',_,_],
    [_,_,_,_,_,_,_,_,_,_],
    [_,'G','G','G','G','G','G','G',_,_],
    [_,_,_,_,_,_,_,_,_,_],
    ['G','G','G','G','G','G','G','G',_,_],
    [_,_,_,_,_,_,_,_,_,_],
    [_,'G','G','G','G','G','G','G',_,_],
    [_,_,_,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
]

UNKNOWN = [
    [_,_,'W','W','W',_,_,_,_,_],
    [_,'W',_,_,_,'W',_,_,_,_],
    [_,_,_,_,_,'W',_,_,_,_],
    [_,_,_,_,'W',_,_,_,_,_],
    [_,_,_,'W',_,_,_,_,_,_],
    [_,_,_,'W',_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
    [_,_,_,'W',_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
]

PARTLY_CLOUDY = [
    [_,_,'Y',_,_,_,_,_,_,_],
    [_,'Y',_,'Y',_,_,_,_,_,_],
    ['Y',_,'W','W',_,_,_,_,_,_],
    [_,'Y','W','W','W','W',_,_,_,_],
    [_,_,'W','W','W','W','W',_,_,_],
    [_,_,'G','G','G','G','G',_,_,_],
    [_,_,_,'G','G','G',_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_],
]

PALETTE = {
    'Y': (255, 220, 0),
    'W': (220, 220, 220),
    'G': (150, 150, 150),  # Gray for clouds/fog
    'B': (80, 140, 255),
    'R': (255, 60, 60),
}


def get_icon_for_code(weather_code):
    if weather_code == 0:
        return SUN
    elif weather_code == 1:
        return PARTLY_CLOUDY
    elif weather_code in [2, 3]:
        return CLOUD
    elif weather_code in [45, 48]:
        return FOG
    elif weather_code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]:
        return RAIN
    elif weather_code in [71, 73, 75, 77, 85, 86]:
        return SNOW
    elif weather_code in [95, 96, 99]:
        return STORM
    else:
        return UNKNOWN


# -------- RIDDLES --------
RIDDLES = [
    "What has keys but can't open locks?",
    "I speak without a mouth and hear without ears. What am I?",
    "What comes once in a minute, twice in a moment, but never in a thousand years?",
    "What can travel around the world while staying in a corner?",
    "What has hands but can't clap?",
    "What has a head and a tail but no body?",
    "The more you take, the more you leave behind. What are they?",
    "What has cities, but no houses; forests, but no trees; and water, but no fish?",
    "I'm tall when I'm young, and I'm short when I'm old. What am I?",
    "What begins with T, ends with T, and has T in it?",
]


def get_todays_riddle():
    today = date.today()
    day_seed = today.year * 10000 + today.month * 100 + today.day
    rng = random.Random(day_seed)
    return rng.choice(RIDDLES)


def wrap_text(text, chars_per_line):
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        if current_line == "":
            current_line = word
        elif len(current_line) + 1 + len(word) <= chars_per_line:
            current_line += " " + word
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines


class SubwayDisplay:

    def __init__(self):
        options = RGBMatrixOptions()
        options.rows = 64
        options.cols = 64
        options.chain_length = 1
        options.parallel = 1
        options.hardware_mapping = 'regular'
        options.gpio_slowdown = 4
        options.brightness = 60

        self.matrix = RGBMatrix(options=options)
        self.canvas = self.matrix.CreateFrameCanvas()

        self.font_small = graphics.Font()
        self.font_large = graphics.Font()

        try:
            self.font_small.LoadFont('/usr/local/share/rpi-rgb-led-matrix/fonts/5x8.bdf')
            self.font_large.LoadFont('/usr/local/share/rpi-rgb-led-matrix/fonts/6x10.bdf')
        except Exception as e:
            print(f"WARNING: Could not load font: {e}")

        # Train colors
        self.color_e_train = graphics.Color(0, 57, 166)
        self.color_7_train = graphics.Color(185, 51, 173)

        # General colors
        self.color_white = graphics.Color(255, 255, 255)
        self.color_yellow = graphics.Color(255, 220, 0)
        self.color_green = graphics.Color(0, 220, 0)
        self.color_red = graphics.Color(220, 0, 0)
        self.color_dim = graphics.Color(100, 100, 100)
        self.color_cyan = graphics.Color(0, 200, 200)

        # Bondi page assets
        self.font_bondi_label = graphics.Font()
        self.font_bondi_value = graphics.Font()
        try:
            self.font_bondi_label.LoadFont('/usr/local/share/rpi-rgb-led-matrix/fonts/4x6.bdf')
            self.font_bondi_value.LoadFont('/usr/local/share/rpi-rgb-led-matrix/fonts/4x6.bdf')
        except Exception as e:
            print(f"WARNING bondi fonts: {e}")
            self.font_bondi_label = self.font_small
            self.font_bondi_value = self.font_small

        try:
            img = Image.open(BONDI_IMAGE_PATH)
            img.thumbnail((self.matrix.width, self.matrix.height), Image.LANCZOS)
            img = img.convert("RGB")
            # Cast to plain int — SetPixel rejects numpy.uint8
            self.bondi_pixels = [
                [(int(r), int(g), int(b)) for (r, g, b) in
                 [img.getpixel((x, y)) for x in range(img.width)]]
                for y in range(img.height)
            ]
            print("Bondi image loaded OK")
        except Exception as e:
            print(f"WARNING: could not load Bondi image: {e}")
            self.bondi_pixels = None

        # Shared data (protected by lock)
        self.train_data = {'E': [], '7': []}
        self.weather_data = {'temp': None, 'icon_pixels': None}
        self.market_data = {'dow': None, 'change': None, 'vix': None}
        self.lock = threading.Lock()

        # Page rotation for riddle window
        self.pages = [self.draw_subway_page, self.draw_riddle_page]
        self.current_page_index = 0
        self.last_switch_time = time.time()

        # Riddle scroll state
        self.riddle_scroll_y = 0
        self.riddle_scroll_pause = 0
        self.riddle_scroll_direction = 1
        self.riddle_cached_date = None
        self.riddle_cached_lines = []
        self._riddle_reset_after_pause = False

    # -------- Schedule --------

    def is_active_hours(self):
        hour = datetime.now().hour
        return ACTIVE_START_HOUR <= hour < ACTIVE_END_HOUR

    def is_riddle_window(self):
        now = datetime.now()
        return now.hour == 20 and now.minute < 30

    def is_market_window(self):
        """Show markets for MARKET_SHOW_DURATION_SEC at the top of every MARKET_INTERVAL_MINUTES."""
        now = datetime.now()
        return (now.minute % MARKET_INTERVAL_MINUTES == 0
                and now.second < MARKET_SHOW_DURATION_SEC)

    def is_bondi_window(self):
        """Show Bondi DOW page at specific minutes past the hour."""
        now = datetime.now()
        return (now.minute in BONDI_SHOW_MINUTES
                and now.second < BONDI_SHOW_DURATION_SEC)

    # -------- Draw Pixel-Art Icon --------

    def draw_icon(self, icon, x_offset, y_offset):
        for row_idx, row in enumerate(icon):
            for col_idx, color_key in enumerate(row):
                if color_key is None:
                    continue
                r, g, b = PALETTE[color_key]
                self.canvas.SetPixel(x_offset + col_idx, y_offset + row_idx, r, g, b)

    # -------- Weather --------

    def get_weather(self):
        try:
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                'latitude': LATITUDE,
                'longitude': LONGITUDE,
                'current': 'temperature_2m,weather_code',
                'temperature_unit': 'fahrenheit',
                'timezone': 'America/New_York',
            }
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            temp = int(data['current']['temperature_2m'])
            code = data['current']['weather_code']
            return {'temp': temp, 'icon_pixels': get_icon_for_code(code)}
        except Exception as e:
            print(f"Error fetching weather: {e}")
            return {'temp': None, 'icon_pixels': UNKNOWN}

    # -------- Markets --------

    def get_market_data(self):
        try:
            dow_ticker = yf.Ticker("^DJI")
            vix_ticker = yf.Ticker("^VIX")

            dow_info = dow_ticker.fast_info
            vix_info = vix_ticker.fast_info

            dow_price = int(dow_info["lastPrice"])
            dow_prev = dow_info["previousClose"]
            dow_change = round(dow_price - dow_prev, 1)

            vix_price = round(vix_info["lastPrice"], 1)

            return {"dow": dow_price, "change": dow_change, "vix": vix_price}
        except Exception as e:
            print(f"Error fetching market data: {e}")
            return {"dow": None, "change": None, "vix": None}

    # -------- Trains --------

    def get_arrivals(self, route):
        try:
            cfg = STATIONS[route]
            full_stop = f"{cfg['stop_id']}{cfg['direction']}"

            feed = NYCTFeed(route)
            trains = feed.filter_trips(underway=True)

            arrivals = []
            now = datetime.now()

            for train in trains:
                for st in train.stop_time_updates:
                    if st.stop_id == full_stop:
                        mins = (st.arrival - now).total_seconds() / 60
                        if mins >= WALK_TIME_TO_STATIONS_MINUTES:
                            arrivals.append(int(mins))

            arrivals.sort()
            return arrivals[:3]
        except Exception as e:
            print(f"Error getting arrivals for {route}: {e}")
            return []

    # -------- Update Thread --------

    def update_train_data(self):
        while True:
            for route in ['E', '7']:
                arrivals = self.get_arrivals(route)
                with self.lock:
                    self.train_data[route] = arrivals

            weather = self.get_weather()
            with self.lock:
                self.weather_data = weather

            market = self.get_market_data()
            with self.lock:
                self.market_data = market

            time.sleep(30)

    # -------- Subway Page --------

    def draw_subway_page(self):
        self.canvas.Clear()

        # Weather icon + temp (top-left)
        self.draw_weather()

        # Clock (top-right)
        current_time = datetime.now().strftime("%H:%M")
        graphics.DrawText(self.canvas, self.font_small, 34, 8, self.color_white, current_time)

        # Train lines
        self.draw_train_line(24, 'E', self.color_e_train)
        self.draw_train_line(46, '7', self.color_7_train)

    def draw_weather(self):
        with self.lock:
            weather = self.weather_data.copy()

        if weather['icon_pixels']:
            self.draw_icon(weather['icon_pixels'], x_offset=2, y_offset=1)

        if weather['temp'] is not None:
            graphics.DrawText(self.canvas, self.font_small, 14, 8,
                              self.color_white, f"{weather['temp']}F")

    def draw_train_circle(self, x, y, radius, color):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius:
                    self.canvas.SetPixel(x + dx, y + dy,
                                         color.red, color.green, color.blue)

    def draw_train_line(self, y_pos, route, color):
        # Colored circle with route letter
        circle_x = 8
        circle_y = y_pos
        circle_radius = 6
        self.draw_train_circle(circle_x, circle_y, circle_radius, color)
        graphics.DrawText(self.canvas, self.font_large, circle_x - 2, circle_y + 4,
                          self.color_white, route)

        # Station name
        station_name = STATIONS[route]['name']
        graphics.DrawText(self.canvas, self.font_small, 18, y_pos,
                          self.color_white, station_name)

        # Arrival times
        with self.lock:
            arrivals = self.train_data[route]

        y_offset = y_pos + 10
        if not arrivals:
            graphics.DrawText(self.canvas, self.font_small, 18, y_offset,
                              self.color_white, "No data")
        else:
            parts = []
            for minutes in arrivals:
                if minutes == 0:
                    parts.append("Now")
                elif minutes == 1:
                    parts.append("1m")
                else:
                    parts.append(f"{minutes}m")

            text_color = self.color_yellow if arrivals[0] <= 2 else self.color_white
            graphics.DrawText(self.canvas, self.font_small, 18, y_offset,
                              text_color, ", ".join(parts))

    # -------- Riddle Page --------

    def draw_riddle_page(self):
        self.canvas.Clear()

        today = date.today()
        if self.riddle_cached_date != today:
            riddle = get_todays_riddle()
            self.riddle_cached_lines = wrap_text(riddle, 12)
            self.riddle_cached_date = today
            self.riddle_scroll_y = 0
            self.riddle_scroll_pause = 20
            self._riddle_reset_after_pause = False

        lines = self.riddle_cached_lines
        line_height = 10
        display_height = 64

        # Header scrolls with content
        header_y = 8 - self.riddle_scroll_y
        if 0 < header_y <= display_height:
            graphics.DrawText(self.canvas, self.font_small, 2, header_y,
                              self.color_yellow, "RIDDLE:")

        # Wrapped riddle lines
        y_start = 20
        for i, line in enumerate(lines):
            y = y_start + i * line_height - self.riddle_scroll_y
            if 0 < y <= display_height:
                graphics.DrawText(self.canvas, self.font_small, 2, y,
                                  self.color_white, line)

        total_content_height = y_start + len(lines) * line_height + 4
        max_scroll = max(0, total_content_height - display_height)

        if max_scroll == 0:
            return

        # Pause at top/bottom before scrolling
        if self.riddle_scroll_pause > 0:
            self.riddle_scroll_pause -= 1
            if self.riddle_scroll_pause == 0 and self._riddle_reset_after_pause:
                self.riddle_scroll_y = 0
                self._riddle_reset_after_pause = False
                self.riddle_scroll_pause = 20
            return

        self.riddle_scroll_y += 1
        if self.riddle_scroll_y >= max_scroll:
            self.riddle_scroll_y = max_scroll
            self.riddle_scroll_pause = 50
            self._riddle_reset_after_pause = True

    # -------- Markets Page --------

    def draw_market_page(self):
        self.canvas.Clear()

        with self.lock:
            data = self.market_data.copy()

        # ---- Header: "MARKETS" with a thin separator line ----
        graphics.DrawText(self.canvas, self.font_small, 2, 8,
                          self.color_yellow, "MARKETS")

        # Dim separator line
        for x in range(2, 62):
            self.canvas.SetPixel(x, 10, 60, 60, 60)

        # ---- DOW section ----
        if data["dow"] is not None:
            graphics.DrawText(self.canvas, self.font_small, 2, 20,
                              self.color_dim, "DOW")

            # Price in large font
            dow_str = f"{data['dow']:,}"
            graphics.DrawText(self.canvas, self.font_large, 2, 32,
                              self.color_white, dow_str)

            # Change with pixel-art arrow
            if data["change"] is not None:
                is_up = data["change"] >= 0
                color = self.color_green if is_up else self.color_red
                ar, ag, ab = (0, 220, 0) if is_up else (220, 0, 0)

                # Draw 5x5 arrow with SetPixel directly
                if is_up:
                    arrow_pixels = [
                        (2, 0), (1, 1), (2, 1), (3, 1),
                        (0, 2), (2, 2), (4, 2), (2, 3), (2, 4),
                    ]
                else:
                    arrow_pixels = [
                        (2, 0), (2, 1), (0, 2), (2, 2),
                        (4, 2), (1, 3), (2, 3), (3, 3), (2, 4),
                    ]
                for px, py in arrow_pixels:
                    self.canvas.SetPixel(2 + px, 35 + py, ar, ag, ab)

                sign = "+" if is_up else ""
                change_str = f"{sign}{data['change']}"
                graphics.DrawText(self.canvas, self.font_small, 10, 42,
                                  color, change_str)
        else:
            graphics.DrawText(self.canvas, self.font_small, 2, 20,
                              self.color_dim, "DOW --")

        # Dim separator
        for x in range(2, 62):
            self.canvas.SetPixel(x, 46, 60, 60, 60)

        # ---- VIX section ----
        graphics.DrawText(self.canvas, self.font_small, 2, 54,
                          self.color_dim, "VIX")

        if data["vix"] is not None:
            v = data["vix"]

            # Color-coded value
            if v < 15:
                vix_color = self.color_green
            elif v < 25:
                vix_color = self.color_yellow
            else:
                vix_color = self.color_red

            graphics.DrawText(self.canvas, self.font_large, 22, 54,
                              vix_color, f"{v}")

            # Small bar gauge underneath (2px tall)
            bar_width = int(min(60, max(0, v)) * 0.9)
            for x in range(bar_width):
                self.canvas.SetPixel(2 + x, 58, vix_color.red, vix_color.green, vix_color.blue)
                self.canvas.SetPixel(2 + x, 59, vix_color.red, vix_color.green, vix_color.blue)
        else:
            graphics.DrawText(self.canvas, self.font_small, 22, 54,
                              self.color_dim, "--")

    # -------- Bondi DOW Page --------

    def _draw_bubble(self, dow_value):
        """Render the speech-bubble overlay with the DOW price."""
        bx, by, bw, bh = BUBBLE_X, BUBBLE_Y, BUBBLE_W, BUBBLE_H
        bg_r, bg_g, bg_b = 10, 10, 10
        br_r, br_g, br_b = 200, 200, 200

        # Fill
        for y in range(by + 1, by + bh - 1):
            for x in range(bx + 1, bx + bw - 1):
                self.canvas.SetPixel(x, y, bg_r, bg_g, bg_b)

        # Border (with rounded corners by skipping the true corner pixels)
        for x in range(bx + 1, bx + bw - 1):
            self.canvas.SetPixel(x, by,          br_r, br_g, br_b)
            self.canvas.SetPixel(x, by + bh - 1, br_r, br_g, br_b)
        for y in range(by + 1, by + bh - 1):
            self.canvas.SetPixel(bx,          y, br_r, br_g, br_b)
            self.canvas.SetPixel(bx + bw - 1, y, br_r, br_g, br_b)

        # Tail pixels pointing down-left
        self.canvas.SetPixel(bx + 4, by + bh,     br_r, br_g, br_b)
        self.canvas.SetPixel(bx + 3, by + bh + 1, br_r, br_g, br_b)

        # Live value
        val_str = f"{int(dow_value):,}" if dow_value is not None else "------"
        graphics.DrawText(self.canvas, self.font_bondi_value,
                          bx + 3, by + 8,
                          graphics.Color(255, 255, 255), val_str)

    def draw_bondi_page(self):
        """Full-screen portrait with live DOW speech-bubble."""
        self.canvas.Clear()

        # Blit portrait
        if self.bondi_pixels:
            try:
                for y, row in enumerate(self.bondi_pixels):
                    for x, (r, g, b) in enumerate(row):
                        self.canvas.SetPixel(x, y, r, g, b)
            except Exception as e:
                print(f"ERROR drawing bondi pixels: {e}")

        # Overlay bubble
        with self.lock:
            dow = self.market_data.get("dow")
        self._draw_bubble(dow)

    # -------- Main Loop --------

    def run(self):
        threading.Thread(target=self.update_train_data, daemon=True).start()
        time.sleep(2)

        try:
            while True:
                if not self.is_active_hours():
                    self.matrix.Clear()
                    self.matrix.brightness = 0
                    time.sleep(60)
                    continue
                else:
                    self.matrix.brightness = 60

                # Priority 1: Bondi DOW page (specific minutes past the hour)
                if self.is_bondi_window():
                    self.draw_bondi_page()

                # Priority 2: Market window (every 10 min for 1 min)
                elif self.is_market_window():
                    self.draw_market_page()

                # Priority 3: Riddle window (8:00-8:30pm, alternates with subway)
                elif self.is_riddle_window():
                    now = time.time()
                    if now - self.last_switch_time >= 30:
                        self.current_page_index = (self.current_page_index + 1) % len(self.pages)
                        self.last_switch_time = now
                    self.pages[self.current_page_index]()

                # Default: Subway page
                else:
                    self.current_page_index = 0
                    self.draw_subway_page()

                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                time.sleep(0.1)

        except KeyboardInterrupt:
            print("\nExiting...")
            self.matrix.Clear()


# -------- Network Check --------

def ping_google():
    print("Waiting for network...")
    while True:
        try:
            response = requests.get('https://www.google.com', timeout=5)
            if response.status_code == 200:
                print("Network is ready")
                return
        except:
            print("Network not ready, retrying...")
        time.sleep(10)


# -------- Run --------

if __name__ == "__main__":
    ping_google()

    print("MTA Subway Display Starting...")
    print(f"E Train: {STATIONS['E']['name']} ({STATIONS['E']['direction']}bound)")
    print(f"7 Train: {STATIONS['7']['name']} ({STATIONS['7']['direction']}bound)")
    print(f"Markets: every {MARKET_INTERVAL_MINUTES}min for {MARKET_SHOW_DURATION_SEC}s")
    print("Press Ctrl+C to exit\n")

    display = SubwayDisplay()
    display.run()