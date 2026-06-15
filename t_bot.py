from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, CallbackQuery
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)
from telegram.constants import ParseMode

import logging

from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timedelta, date
import calendar

import pandas as pd
from functools import wraps

import os
import json

from warnings import filterwarnings
from telegram.warnings import PTBUserWarning

filterwarnings(action="ignore", message=r".*CallbackQueryHandler", category=PTBUserWarning)

TOKEN = '8436152259:AAGgYgp1emDODTian1Bbrj8pXMTKyi73Oig'

calendar_dict = {}
tasks_dict = {}

## _________Состояния для сообщений userа

WAITING_FOR_DATE = 0
WAITING_FOR_TASKS = 1


WAITING_FOR_DATE_C = 10
WAITING_FOR_TASKS_C = 11
WAITING_FOR_DATE_TIME_C = 12
WAITING_FOR_DATE_SHARE_C = 13
WAITING_FOR_USERNAME = 14
WAITING_FOR_CONFIRMATION = 15


def save_data():
    data = []

    data_dict = set(tasks_dict | calendar_dict)
    for username in data_dict:
        data.append({
            'user_name': username,
            'todo_list_info': tasks_dict.get(username, {}),
            'calendar_info': calendar_dict.get(username, {})
        })
    
    df = pd.DataFrame(data)
    df['todo_list_info'] = df['todo_list_info'].apply(json.dumps)
    df['calendar_info'] = df['calendar_info'].apply(json.dumps)

    df.to_csv('bot_data.csv', index=False, encoding='utf-8')

expected_columns = ['user_name', 'todo_list_info', 'calendar_info']

def load_data():
    if not os.path.exists('bot_data.csv'):
        return pd.DataFrame(columns=expected_columns)
    
    df = pd.read_csv('bot_data.csv')

    if df.empty:
        return pd.DataFrame(columns=expected_columns)

    for col in ['user_name', 'todo_list_info', 'calendar_info']:
        if col not in df.columns:
            df[col] = None

    df['todo_list_info'] = df['todo_list_info'].apply(lambda x: json.loads(x) if pd.notna(x) else [])
    df['calendar_info'] = df['calendar_info'].apply(lambda x: json.loads(x) if pd.notna(x) else [])

    df = df.reindex(columns=expected_columns)

    return df

df = load_data()
print(df.columns)
print(df.head())


def with_user(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwards):
        global tasks_dict, calendar_dict, df

        if not update or not update.effective_user:
            context.user_data['user_id'] = None
            return await func(update, context, *args, **kwards)
        
        user = update.effective_user
        context.user_data['user_name'] = user.username
        context.user_data['user_id'] = user.id

        if user.username in df['user_name'].values:
            row = df[df['user_name'] == user.username].iloc[0]

            tasks_dict[user.username] = json.loads(row['todo_list_info'] or "{}")
            calendar_dict[user.username] = json.loads(row['calendar_info'] or "{}")

        return await func(update, context, *args, **kwards)
    return wrapper


    #     if update and update.effective_user:
    #         context.user_data['user_id'] = None
    #         user = update.effective_user
    #         if not(df['user_name'].isin([user.username]).any()):
    #             new_df = pd.DataFrame({'user_name': user.username, 'todo_list_info': [{}], 'calendar_info': [{}]})

    #             context.user_data['user_name'] = user.username
    #             context.user_data['user_id'] = user.id
    #             # df = pd.concat([df, new_df], ignore_index=True)

    #         else:
    #             context.user_data['user_name'] = user.username
    #             context.user_data['user_id'] = user.id

    #             tasks_dict[user.username] = df.loc[df['user_name'] == user.username, 'todo_list_info'].iloc[0]
    #             calendar_dict[user.username] = df.loc[df['user_name'] == user.username, 'calendar_info'].iloc[0]
    #     else:
    #         context.user_data['user_id'] = None
    #     return await func(update, context, *args, **kwards)
    # return wrapper


## _________Keyboards 

def todo_menu():
    return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(text='календарь', callback_data='cmd_calendar'),
                InlineKeyboardButton(text='создать список', callback_data='todomenu_create_tasks')
            ],
            [
                InlineKeyboardButton(text='отметить выполненым', callback_data='todomenu_done_tasks')
            ],
            [
                InlineKeyboardButton(text='посмотреть список на сегодня', callback_data='todomenu_see_tasks')
            ]
        ])


def calendar_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(text='список дел', callback_data='cmd_todo_list'),
            InlineKeyboardButton(text='открыть календарь', callback_data='Calendarmenu_show')
        ],
        [
            InlineKeyboardButton(text='закрыть слот в календаре', callback_data='calendaractions_slot')
        ],
        [
            InlineKeyboardButton(text='поделится календарем', callback_data='Calendarmenu_share')
        ]
    ])


## _________Функции для списка дел

def find_number(task):
    num = ''
    i = 0

    while task[i] != '.':
        num += task[i]
        i += 1
    return int(num)


def tasks_done(done_tasks_list: list[str], all_tasks_list: list[str]):
    new_tasks = []

    for task in all_tasks_list:
        new_task = [i.strip() for i in task.split('.')]
        if not task:
            continue
        if new_task[0] in done_tasks_list or new_task[1] in done_tasks_list:
            new_tasks.append(f"<s>{''.join(task)}</s>")
        else:
            new_tasks.append(task)
    
    return new_tasks
        

def validate_and_parse_date(text):
    today = datetime.now().date()
    date_str = today.strftime('%d.%m')
    
    if text == 'сегодня':
        return date_str
    elif text == 'завтра':
        return (today + timedelta(days=1)).strftime('%d.%m')
    else:
        try:
            dt = datetime.strptime(text.strip(), '%d.%m')
            return dt.strftime('%d.%m')
        except ValueError:
            return None
    

## _________Команда /start: описание бота, действия с календарем и todo листом

@with_user
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global df
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(text='список дел', callback_data='cmd_todo_list'),
                InlineKeyboardButton(text='календарь', callback_data='cmd_calendar')
            ]
        ]
    )

    user_name = update.effective_user.full_name
    sent_message = await update.message.reply_text(f"здравствуйте, {user_name}!\n\n"
                         "в этом боте вы сможете:\n\n<b>1)</b> список дел:\n  ⇝ создать список дел, добавить в него любые дела в любой момент;\n"
                         "  ⇝ отметить дело или дела выполнеными;\n  ⇝ посмотреть дела на сегодня\n\n"
                         "<b>2)</b> календарь:\n  ⇝ посмотреть календарь в различных форматах;\n  ⇝ занять слот в календаре делом;\n  ⇝ поделится календарем с другим человеком, есть возможность скрыть все дела или оставить их открытыми\n\n"
                         "что откроем?", reply_markup=keyboard, parse_mode=ParseMode.HTML)
    
    chat_id = update.effective_chat.id
    message_id = sent_message.message_id
    
    await context.bot.pin_chat_message(chat_id=chat_id, message_id=message_id, disable_notification=True)


@with_user
async def todo_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = todo_menu()

    await query.message.reply_text(
        "выберите действие с todo листом:",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )


@with_user
async def todo_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data
        message = query.message
    else:
        data = 'todomenu_create_tasks'
        message = update.message

    todo_command = data[9:]
    context.user_data['todo_command'] = todo_command

    if todo_command == 'create_tasks':
        await message.reply_text(
            "на какой день нужно записать дела?\n\n"
            "напишите дату в формате ДД.ММ или текстом (бот распознает слова: 'сегодня', 'завтра')\n\n"
            "например: 'сегодня' или '25.01'\n\n"
            "отмена диалога: /cancel"
        )
        return WAITING_FOR_DATE
    elif todo_command == 'done_tasks':
        await message.reply_text(
            "дела, какого дня выполнены?\n\n"
            "напишите дату в формате ДД.ММ или текстом (бот распознает слова: 'сегодня', 'завтра')\n\n"
            "например: 'сегодня' или '25.01'\n\n"
            "отмена диалога: /cancel"
        )
        return WAITING_FOR_DATE
    elif todo_command == 'see_tasks':
        user_name = context.user_data['user_name']

        date_obj = datetime.now().date()
        date_str = date_obj.strftime('%d.%m')
        
        if date_str in tasks_dict[user_name]:
            new_list = [''.join(tasks_dict[user_name][date_str][i]) for i in range(len(tasks_dict[user_name][date_str]))]
            tasks_useble_text = '\n'.join(new_list)

            await query.message.reply_text(
                f"список дел на сегодня:\n\n{tasks_useble_text}",
                parse_mode=ParseMode.HTML
            )

            keyboard = todo_menu()

            await query.message.reply_text("выберите действие с todo листом:", reply_markup=keyboard, parse_mode=ParseMode.HTML)
        else:
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(text='да', callback_data='wait_date_yes'),
                        InlineKeyboardButton(text='нет', callback_data='wait_date_no')
                    ]
                ]
            )

            await message.edit_text("похоже у вас нет дел на сегодня. составим список?\n\nотмена диалога: /cancel", reply_markup=keyboard)


@with_user
async def process_today_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data

    if data == 'wait_date_yes':
        date_obj = datetime.now().date()
        date_str = date_obj.strftime('%d.%m')

        normalized_date = validate_and_parse_date(date_str)

        if normalized_date is None:
            await query.message.reply_text(
                "<b>неверный формат даты</b>\n\nнапишите дату в формате <b>ДД.ММ</b> или сеогдня/завтра\n\nотмена диалога: /cancel",
                parse_mode=ParseMode.HTML
            )
            return WAITING_FOR_DATE
        
        context.user_data['date'] = normalized_date
        context.user_data['todo_command'] = 'create_tasks'

        await query.message.reply_text(
            f"записываем дела на <b>{normalized_date}</b>\n\n"
            "теперь напишите список дел на этот день.\n  ⇝ список дел напишите через запятую\n\nотмена диалога: /cancel",
            parse_mode=ParseMode.HTML
        )
        return WAITING_FOR_TASKS
    else:
        keyboard = todo_menu()

        await query.message.reply_text("выберите действие с todo листом:", reply_markup=keyboard, parse_mode=ParseMode.HTML)



@with_user
async def process_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_date = update.message.text.strip().lower()
    normalized_date = validate_and_parse_date(user_date)

    if normalized_date is None:
        await update.message.reply_text(
            "<b>неверный формат даты</b>\n\nнапишите дату в формате <b>ДД.ММ</b> или сеогдня/завтра\n\nотмена диалога: /cancel",
            parse_mode=ParseMode.HTML
        )
        return WAITING_FOR_DATE
    
    context.user_data['date'] = normalized_date

    todo_command = context.user_data.get('todo_command')

    if todo_command == 'create_tasks':
        await update.message.reply_text(
            f"отлично! записываем дела на <b>{normalized_date}</b>\n\n"
            "теперь напишите список дел на этот день.\n  ⇝ список дел напишите через запятую\n\nотмена диалога: /cancel",
            parse_mode=ParseMode.HTML
        )
        return WAITING_FOR_TASKS
    
    elif todo_command == 'done_tasks':
        user_name = context.user_data['user_name']

        if normalized_date in tasks_dict[user_name]:
            tasks_text = '\n'.join(tasks_dict[user_name][normalized_date])
            await update.message.reply_text(
                f"отлично! отмечаем выполнеными дела на <b>{normalized_date}</b>\n\n"
                f"вот список дел:\n\n{tasks_text}\n\n"
                "теперь напишите список/номера дел, которые надо отметить выполнеными.\n  ⇝ список дел/номера дел напишите через запятую\n\nотмена диалога: /cancel", 
                parse_mode='HTML'        
            )
            return WAITING_FOR_TASKS
        else:
            keyboard = InlineKeyboardMarkup([ 
                    [
                        InlineKeyboardButton(text='создать список', callback_data='done_creat'),
                        InlineKeyboardButton(text='изменить дату', callback_data='done_change'),
                    ]
                ])
            await update.message.reply_text(
                f"на <b>{normalized_date}</b> пока нет дел, возможно вы ввели не ту дату. что сделаем\n\nотмена диалога: /cancel",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            return ConversationHandler.END
        


@with_user
async def handle_done_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    command = data

    if command == 'done_creat':
        context.user_data['todo_command'] = 'create_tasks'
        date = context.user_data.get('date', 'Неизвестная дата')

        await query.message.reply_text(
            f"отлично! записываем дела на <b>{date}</b>\n"
            "теперь напишите список дел на этот день.\n  ⇝ список дел напишите через запятую\n\nотмена диалога: /cancel",
            parse_mode=ParseMode.HTML
        )
        return WAITING_FOR_TASKS
    
    elif command == 'done_change':
        await query.message.reply_text("введите другую дату\n\nотмена диалога: /cancel")
        return WAITING_FOR_DATE


@with_user
async def process_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global df

    date = context.user_data.get('date', 'Неизвестная дата').strip().lower()
    tasks_text = update.message.text.strip()

    print(tasks_text)

    tasks_text_list = [i.strip().lower() for i in tasks_text.split(',')]
    todo_command = context.user_data.get('todo_command')

    user_name = context.user_data['user_name']
    print(user_name)
    print(tasks_dict)
    print(tasks_dict.keys())

    if user_name not in tasks_dict.keys():
        if todo_command == 'create_tasks':
            tasks_text_list = [str(i + 1) + '. ' + tasks_text_list[i] for i in range(len(tasks_text_list))]
            tasks_dict[user_name] = {}
            tasks_dict[user_name][date] = tasks_text_list
    
    elif user_name in tasks_dict.keys() and date in tasks_dict[user_name]:
        if todo_command == 'create_tasks':
            last_number = find_number(tasks_dict[user_name][date][-1]) + 1
            for i in range(len(tasks_text_list)):
                tasks_text_list[i] = str(last_number) + '. ' + tasks_text_list[i]
                last_number += 1
            tasks_dict[user_name][date] += tasks_text_list

        elif todo_command == 'done_tasks':
            tasks_dict[user_name][date] = tasks_done(tasks_text_list, tasks_dict[user_name][date])
    elif date not in tasks_dict[user_name] and todo_command == 'create_tasks':
        tasks_text_list = [str(i + 1) + '. ' + tasks_text_list[i] for i in range(len(tasks_text_list))]
        tasks_dict[user_name][date] = tasks_text_list

    print(tasks_dict[user_name])
    print(date)
    tasks_useble_text = '\n'.join(tasks_dict[user_name][date])

    await update.message.reply_text(
        f"список дел на {date}:\n\n{tasks_useble_text}", 
        parse_mode='HTML'
    )

    user_name = context.user_data['user_name']
    if (df['user_name'].isin([user_name]).any()):
        df.loc[user_name, 'todo_list_info'] = [tasks_dict[user_name]]
    else:
        print(f"user name {user_name} not found")
    
    keyboard = todo_menu()

    await update.message.reply_text("выберите действие с todo листом:", reply_markup=keyboard, parse_mode=ParseMode.HTML)

    return ConversationHandler.END



## _________календарь


import math


days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']


def day_of_the_week(user_date):
    day, month = [int(i) for i in user_date.split('.')]
    right_date = date(2026, month, day)
    
    day_week = days[right_date.weekday()]
    return day_week


def find_time(text):
    time = ''
    i = 0

    while text[i].isdigit():
        time += text[i]
        i += 1
    return (time, i)


def normalize_time(str_time):
    time = f"{str_time.zfill(2)}:00"
    return time


def not_enough_space(text, font, max_width, time):
    if font.getlength(time + ' ' + text) <= max_width:
        return [time + ' ' + text]
    
    words = text.split()
    lines = []
    current_line = time + " "

    for word in words:
        test_line = current_line + word + " "
        if font.getlength(test_line) > max_width:
            lines.append(current_line.strip())
            current_line = word + " "
        else:
            current_line = test_line
    
    if current_line:
        lines.append(current_line.strip())
    
    return lines


def get_dates_range(start_date, end_date, year):
    start = datetime.strptime(start_date + f".{year}", "%d.%m.%Y")
    end = datetime.strptime(end_date + f".{year}", "%d.%m.%Y")

    days_c = (end - start).days + 1

    return [(start + timedelta(days=i)).strftime("%d.%m") for i in range(days_c)]



def get_calendar_representation(date):
    if ':' in date:
        return 'other'
    elif '.' in date or date in ['сегодня', 'завтра']:
        return 'day'
    return 'month'


def get_font_size(base_size, width, height):
    min_side = min(width, height)
    return int(min_side / base_size)


def draw_dotted_line(image, x, y, width):
    for i in range(x, width, 8):
        image.circle(xy=(i, y), radius=1.5, fill='black')


def show_share_calendar(user_date, mode, share_mode, all_info):
    representation_dict = {'day': (1080, 1700), 'month': (4200, 2480), 'other': (600, 470)}
    representation = get_calendar_representation(user_date.lower().strip())
    print(representation)

    if representation in ['day', 'month']:
        width, height = representation_dict[representation]
        if representation == 'month':
            month = int(user_date)
            year = date.today().year
            last_day, day_one = calendar.monthrange(2026, month)[1], 1

            start, end = f"{day_one:02d}.{month:02d}", f"{(last_day):02d}.{month:02d}"
            days_range = get_dates_range(start, end, year)

            start_col = date(year, month, 1).weekday()
            current_col = start_col

            rows = 5

    else:
        date_1, date_2 = user_date.split(':')
        d1, m1 = [int(i) for i in date_1.split('.')] 
        d2, m2 = [int(i) for i in date_2.split('.')] 

        year = date.today().year
        num_day = 7 - date(year, m1, d1).weekday() + 1

        date1, date2 = date(year, m1, d1), date(year, m2, d2)

        days_count = (date2 - date1).days + 1
        rows = math.ceil((days_count - num_day) / 7 + 1)

        w, h = representation_dict[representation]
        width, height = w * 7, h * rows

        days_range = get_dates_range(date_1, date_2, year)

        start_col = date(year, m1, d1).weekday()
        current_col = start_col


    if representation in ['month', 'other']:
        margin = 50
        header_height = 130

        font_size_base, font_size_small = 48, 45

        font_regular = ImageFont.truetype("Anonymous.ttf", font_size_base)
        font_bold = ImageFont.truetype("Anonymous_Bold.ttf", font_size_base)
        font_for_tasks = ImageFont.truetype("Anonymous.ttf", font_size_small)

        cell_width, cell_height = (width - 2 * margin) // 7, (height - header_height) // rows

        img = Image.new('RGB', (width, height), (253, 245, 230))
        draw = ImageDraw.Draw(img)


        for i, day in enumerate(days):
            x = margin + i * cell_width
            text_width = font_bold.getlength(day)
            text_x = x + (cell_width - text_width) // 2

            draw.text(text=day, xy=(text_x, margin), font=font_bold, fill='black')


        for i in range(1, 7):
            x = margin + i * cell_width
            draw.line([(x, header_height), (x, height - margin)], fill='black', width=1)

        current_row = 0

        test_bbox = font_regular.getbbox("01.01")
        task_bbox = font_for_tasks.getbbox("дело")
        task_line_height = test_bbox[3] - test_bbox[1]

        line_height, line_width = test_bbox[3] - test_bbox[1] + 5, test_bbox[2] - test_bbox[0] + 5

        for day in days_range:
            x = margin + current_col * cell_width
            y = header_height + current_row * cell_height

            padding = 20
            content_x, content_y = x + padding, y + padding
            content_width = cell_width - 2 * padding 

            max_task_height = cell_height
            height_break = False

            draw.text((content_x + padding * 2, content_y), day, font=font_regular, fill='black')
            max_task_height -= (line_height + 20 + padding)

            draw.rounded_rectangle((content_x + padding * 1.1, content_y - 5, content_x + 5 + line_width + padding * 2, content_y + line_height + 20), 15, outline='black', width=3)

            task_y = content_y + line_height + padding + 20
            if day in all_info and (mode == 'show' or share_mode == 'open'):
                for tm_task in all_info[day]:
                    tm, index = find_time(tm_task)
                    time = normalize_time(tm)
                    task = tm_task[index:]

                    lines = not_enough_space(task, font_for_tasks, cell_width - padding * 2, time)

                    for line in lines:
                        draw.text((content_x, task_y), line, font=font_for_tasks, fill='black')
                        task_y += line_height
                        max_task_height -= (line_height + task_line_height)
                        if max_task_height - (line_height + task_line_height) < 0:
                            height_break = True
                            break

                    task_y += padding

                    if max_task_height - ((line_height + task_line_height)) < 0 or height_break:
                        draw.text((content_x, task_y), '...', font=font_for_tasks, fill='black')
                        break
            elif share_mode == 'closed' and day not in all_info:
                draw.text((content_x, task_y), 'день свободен', font=font_for_tasks, fill='black')
            
            current_col += 1
            if current_col >= 7:
                current_col = 0
                current_row += 1
        
    if representation == 'day':

        if user_date in ['сегодня', 'завтра']:
            if user_date == 'сегодня':
                date_obj = datetime.now().date()
                user_date = date_obj.strftime('%d.%m')
            else:
                date_obj = datetime.now().date() + timedelta(days=1)
                user_date = date_obj.strftime('%d.%m')


        font_size_base, font_size_small = 40, 37

        font_regular = ImageFont.truetype("Anonymous.ttf", font_size_base)
        font_bold = ImageFont.truetype("Anonymous_Bold.ttf", font_size_base)
        font_for_tasks = ImageFont.truetype("Anonymous.ttf", font_size_small)

        img = Image.new('RGB', (width, height), (253, 245, 230))
        draw = ImageDraw.Draw(img)

        margin = 15
        left_padding = 20

        date_bbox = font_bold.getbbox(user_date)
        date_width, date_height = date_bbox[2] - date_bbox[0], date_bbox[3] - date_bbox[1]

        time_bbox = font_regular.getbbox('00:00')
        time_width, time_height = time_bbox[2] - time_bbox[0], time_bbox[3] - time_bbox[1]

        line_height = int((time_height + margin) * 1.6)
        total_time_height = line_height * 24

        header_y = 70

        x_date, y_date = left_padding * 4, header_y

        draw.text((x_date, y_date), user_date, font=font_bold, fill='black')

        padding_rect = 10
        draw.rounded_rectangle(
            (x_date - padding_rect * 1.5, y_date - padding_rect * 0.5,
            x_date + date_width + padding_rect, y_date + date_height + padding_rect * 1.8),
            15, outline='black', width=2
        )

        week_day = day_of_the_week(user_date)
        x_weekday = x_date + date_width + margin * 4
        draw.text((x_weekday, y_date), week_day, font=font_bold, fill='black')

        closed_times = {}
        if user_date in all_info:
            for task in all_info[user_date]:
                tm, idx = find_time(task)
                task_text = task[idx:].strip()
                closed_times[int(tm)] = task_text
        
        y_start = date_height + header_y * 2
        x_time = left_padding
        x_task = x_time + time_width + margin * 2

        for hour in range(24):
            y_current = y_start + hour * line_height

            time_str = normalize_time(str(hour))
            draw.text((x_time, y_current), time_str, font=font_regular, fill='black')

            line_start_x = x_task - margin
            line_end_x = width - margin * 2
            draw_dotted_line(draw, line_start_x, y_current + time_height * 1.8, line_end_x)

            task_x, task_y = x_task, y_current + 3

            if hour in closed_times:
                if mode == 'show' or share_mode == 'open':
                    draw.text((task_x, task_y), closed_times[hour], font=font_for_tasks, fill='black')
            else:
                if share_mode == 'closed':
                    draw.text((task_x, task_y), 'свободно', font=font_for_tasks, fill=(87, 107, 47))
    
    name = 'calendar.png'
    img.save(name)
    return name, representation



def correct_tasks(info):
    new_info = ' '.join(info)
    info_list = []
    if ';' in new_info:
        info_list = new_info.split(';')
    else:
        info_list.append(new_info)
    return info_list


def select_time(items):
    time = ''
    i = 0
    while items[i].isdigit():
        time += items[i]
        i += 1
    return int(time)



@with_user
async def calendar_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = calendar_menu()

    await query.message.reply_text(
        "выберите действие с календарем",
        reply_markup=keyboard
    )


@with_user
async def calendar_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    command = data[13:]
    context.user_data['calendar_command'] = command
    
    if command == 'show':
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(text='день', callback_data='calendaractions_open_day'),
                InlineKeyboardButton(text='месяц', callback_data='calendaractions_open_month'),
                InlineKeyboardButton(text='другое', callback_data='calendaractions_open_other')
            ]
        ])

        await query.message.edit_text(
            "в каком формате открыть календарь?\n\nотмена диалога: /cancel", 
            reply_markup=keyboard
        )
    
    elif command == 'share':
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(text='да', callback_data='user_yes'),
                InlineKeyboardButton(text='нет', callback_data='user_no')
            ]
        ])

        await query.message.edit_text(
            "человек, которому вы хотите отправить календарь использует этот бот?\n\nотмена диалога: /cancel",
            reply_markup=keyboard
        )


@with_user
async def open_format_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text_dict = {'show': [
            "введите день, который нужно показать\n\nнапишите дату в формате ДД.ММ или текстом, если это сегодня или завтра\nнапример:\n'сегодня' или '25.01'", 
            "введите номер или название месяца, который нужно показать\n\nнапример:\n'февраль' или '2'",
            "введите отрезок, который нужно показать\n\nотрезок напишите в формате 'ДД.ММ:ДД.ММ' или 'от ДД.ММ до ДД.ММ'\n\nнапример:\n'12.01:25.01' или 'от 3.10 до 10.11'"
        ],
        'share': [
            "введите день, который нужно отправить\n\nнапишите дату в формате ДД.ММ или текстом, если это сегодня или завтра\nнапример:\n'сегодня' или '25.01'",
            "введите номер или название месяца, который нужно отправить\n\nнапример:\n'февраль' или '2'",
            "введите отрезок, который нужно отправить\n\nотрезок напишите в формате 'ДД.ММ:ДД.ММ' или 'от ДД.ММ до ДД.ММ'\n\nнапример:\n'12.01:25.01' или 'от 3.10 до 10.11'"
        ],
        'slot': "введите дату, когда нужно закрыть слот\n\nнапишите дату в формате ДД.ММ или текстом, если это сегодня или завтра\nнапример:\n'сегодня' или '25.01'"}

    query = update.callback_query
    await query.answer()

    data = query.data
    calendar_command = context.user_data.get('calendar_command')

    if calendar_command in ['show', 'share']:
        if calendar_command == 'show':
            command = data[len('calendaractions_open_'):] #calendaractions_open_ calendaractions_share_day
        elif calendar_command == 'share':
            command = data[len('calendaractions_share_'):]

        context.user_data['open_or_share'] = calendar_command
        context.user_data['format_to_open'] = command

        if command == 'day':
            await query.message.edit_text(text_dict[calendar_command][0] + "\n\nотмена диалога: /cancel")
            return WAITING_FOR_DATE_C
        
        elif command == 'month':
            await query.message.edit_text(text_dict[calendar_command][1] + "\n\nотмена диалога: /cancel")
            return WAITING_FOR_DATE_C
        
        elif command == 'other':
            await query.message.edit_text(text_dict[calendar_command][2] + "\n\nотмена диалога: /cancel")
            return WAITING_FOR_DATE_C
    else: # calendar_command == 'slot':
        calendar_command = 'slot'
        context.user_data['calendar_command'] = calendar_command
        await query.message.reply_text(str(text_dict[calendar_command]) + "\n\nотмена диалога: /cancel")
        return WAITING_FOR_DATE_C
    

@with_user
async def process_date_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_date = update.message.text.strip().lower()
    data = context.user_data

    format_to_open = data.get('format_to_open')
    calendar_command = context.user_data.get('calendar_command')

    month_name = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']

    if format_to_open == 'day':
            normalized_date = validate_and_parse_date(user_date)

            if normalized_date is None:
                await update.message.reply_text(
                    "<b>неверный формат даты</b>\n\nнапишите дату в формате <b>ДД.ММ</b> или сеогдня, завтра", 
                    parse_mode='HTML'
                )
                return WAITING_FOR_DATE_C

            context.user_data['dateC'] = normalized_date
            num = int(normalized_date.split('.')[1])
    
    elif format_to_open == 'month':
        
        try:
            num = int(user_date)
            if not(num >= 1 and num <= 12):
                await update.message.reply_text(
                    "<b>месяц должен быть от 1 до 12</b>\nпопробуйте снова\n\nотмена диалога: /cancel", 
                    parse_mode='HTML'
                )
                return WAITING_FOR_DATE_C
        

        except ValueError:
            name = user_date.strip().lower()
            if name not in month_name:
                await update.message.reply_text(
                    "<b>неверный формат.</b>\nвведите число от 1 до 12 или названия месяца. например: февраль\n\nотмена диалога: /cancel"
                )
                return WAITING_FOR_DATE_C
    elif format_to_open == 'other':
        day1, day2 = user_date.strip().split(':')

        normalized_date1 = validate_and_parse_date(day1)
        normalized_date2 = validate_and_parse_date(day2)

        if normalized_date1 is None or normalized_date2 is None:
            await update.message.reply_text(
                "<b>неверный формат даты</b>\n\nнапишите дату в формате ДД.ММ:ДД.ММ или от ДД.ММ до ДД.ММ\n\nотмена диалога: /cancel", 
                parse_mode='HTML'
            )
            return WAITING_FOR_DATE_C
        
        month_name.append(f"период с {day1} по {day2}")
        num = len(month_name)

    if calendar_command in ['show', 'share']:
        open_or_share = data.get('open_or_share')
        if open_or_share == 'share':
            share_mode = data.get('share_mode')
        else:
            share_mode = None

        user_name = context.user_data['user_name']
        if user_name not in calendar_dict:
            await update.message.reply_text("Ваш календарь пока пуст", parse_mode=ParseMode.HTML)
        else:
            photo_name, representation = show_share_calendar(user_date, open_or_share, share_mode, calendar_dict[user_name])

            if representation == 'day':
                if user_date in ['сегодня', 'завтра']:
                    if user_date == 'сегодня':
                        date_obj = datetime.now().date()
                        show_text = date_obj.strftime('%d.%m')
                    else:
                        date_obj = datetime.now().date() + 1
                        show_text = date_obj.strftime('%d.%m')
            elif representation == 'month':
                if user_date in [str(i) for i in range(1, 13)]:
                    show_text = month_name[int(user_date) - 1]
                else:
                    show_text = user_date
            else:
                show_text = month_name[-1]

            await update.message.reply_photo(
                photo=open(photo_name, 'rb'), 
                caption=f"календарь на {show_text}"
            )
    elif calendar_command == 'slot':
        user_date = update.message.text.strip().lower()
        normalized_date = validate_and_parse_date(user_date)

        if normalized_date is None:
            await update.message.reply_text(
                "<b>неверный формат даты</b>\n\nнапишите дату в формате <b>ДД.ММ</b> или сеогдня, завтра\n\nотмена диалога: /cancel", 
                parse_mode='HTML'
            )
            return WAITING_FOR_DATE_C
        
        context.user_data['dateC'] = normalized_date

        await update.message.reply_text(
            f"отлично! записываем дела на <b>{normalized_date}</b>\n\n"
            "теперь напишите время и дело на этот день, если дел несколько, разделяйте их знаком ';'\n\n<I>** время пишите одной цифрой **</I>\n"
            "например:\n"
            "'11 сходить в магазин' или '10 рабочая встреча; 17 заехать в мастерскую'\n\nотмена диалога: /cancel",
            parse_mode=ParseMode.HTML
        )
        
        return WAITING_FOR_TASKS_C

    keyboard = calendar_menu()

    await update.message.reply_text(
        "что делаем дальше?",
        reply_markup=keyboard
    )

    
@with_user
async def process_tasks_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global calendar_dict

    data = context.user_data
    date = data.get('dateC').strip().lower()

    tasks_text = update.message.text.strip()
    tasks_list = [el.strip() for el in tasks_text.split(';')]
    
    text_list = []
    for el in tasks_list:
        time, index = find_time(el)
        time = normalize_time(time)
        text_list.append(str(time) + ' -' + el[index:])
    
    text = '\n'.join(text_list)

    context.user_data['tasks_list'] = tasks_list    

    await update.message.reply_text(f"На {date} расписание:\n\n{text}")
    keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(text='да', callback_data='tasks_ok'),
                    InlineKeyboardButton(text='нет', callback_data='calendaractions_slot')
                ]
            ])
    await update.message.reply_text("все верно?\n\nотмена диалога: /cancel", reply_markup=keyboard)
    return ConversationHandler.END


@with_user
async def tasks_reliability_processing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global df

    query = update.callback_query
    await query.answer()

    data = query.data

    command = data[6:]
    if command == 'ok':
        date = context.user_data.get('dateC').strip().lower()
        tasks = context.user_data.get('tasks_list')

        user_name = context.user_data['user_name']

        if user_name not in calendar_dict.keys():
            calendar_dict[user_name] = {}
            calendar_dict[user_name][date] = tasks
        elif date in calendar_dict[user_name]:
            calendar_dict[user_name][date].append(tasks)
            calendar_dict[user_name][date] = sorted(calendar_dict[user_name][date], key=select_time)
        else:
            calendar_dict[user_name][date] = tasks
        
        user_name = context.user_data['user_name']
        if (df['user_name'].isin([user_name]).any()):
            df.loc[user_name, 'calendar_info'] = [calendar_dict[user_name]]
        else:
            print(f"user name {user_name} not found")

        keyboard = calendar_menu()

        await query.message.reply_text(
            "что делаем дальше?\n\nотмена диалога: /cancel",
            reply_markup=keyboard
        )
        return ConversationHandler.END


@with_user
async def share_calendar_yes_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    command = data[5:]

    if command == 'yes':
        await query.message.edit_text('введите user name человека, которому хотите отправить календарь\n\nотмена диалога: /cancel')
        return WAITING_FOR_USERNAME
    else:
        context.user_data['give_username'] = None

    keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(text='да', callback_data='Sopen_closed'),
                    InlineKeyboardButton(text='нет', callback_data='Sopen_open')
                ]
            ])

    await query.message.edit_text(
        "нужно ли скрыть все дела?\n\nотмена диалога: /cancel", 
        reply_markup=keyboard
    )


@with_user
async def share_open_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    command = data[6:]

    context.user_data['share_mode'] = command

    keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(text='день', callback_data='calendaractions_share_day'),
                InlineKeyboardButton(text='месяц', callback_data='calendaractions_share_month'),
                InlineKeyboardButton(text='другое', callback_data='calendaractions_share_other'),
            ]
        ])
    
    await query.message.edit_text(
        "в каком формате нужно отправить календарь?\n\nотмена диалога: /cancel", 
        reply_markup=keyboard
    )
    


callback_routes = {
    'cmd_todo_list': todo_list_handler,
    'cmd_calendar': calendar_handler,
}


@with_user
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    print(data)

    handler = callback_routes.get(data)
    if handler:
        await handler(update, context)
    elif data.startswith('todomenu_'):
        await todo_action(update, context)
    elif data.startswith('done_'):
        await handle_done_buttons(update, context)
    elif data.startswith('wait_date'):
        await process_today_list(update, context)
    
    elif data.startswith('Calendarmenu_'):
        await calendar_actions(update, context)
    elif data.startswith('calendaractions_'):
        await open_format_handler(update, context)
    elif data.startswith('user_'):
        await share_calendar_yes_no(update, context)
    elif data.startswith('Sopen_'):
        await share_open_mode(update, context)
    elif data.startswith('tasks_'):
        await tasks_reliability_processing(update, context)

    else:
        await query.edit_message_text(
            text=f"Команда '{data}' не распознана"
        )
        await start(update, context)


@with_user
async def debug_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Any message")

@with_user
async def debug_any_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    print("Any callback")



logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    aplication = ApplicationBuilder().token(TOKEN).build()

    async def global_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data.clear()
        print(context.user_data)

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(text='список дел', callback_data='cmd_todo_list'),
                    InlineKeyboardButton(text='календарь', callback_data='cmd_calendar')
                ]
            ]
        )

        await update.message.reply_text("все действия отменены, выберите следующее действие:", reply_markup=keyboard)
        return ConversationHandler.END
    
    aplication.add_handler(CommandHandler("cancel", global_cancel))

    todo_conv = ConversationHandler(
        entry_points=[
            CommandHandler("start_todo", todo_action),
            CallbackQueryHandler(todo_action, pattern='^todomenu_'),

            CommandHandler("done_choices", handle_done_buttons),
            CallbackQueryHandler(handle_done_buttons, pattern='^done_'),
            
            CommandHandler("creat_new_list", process_today_list),
            CallbackQueryHandler(process_today_list, pattern='^wait_date_')
        ],
        states={
            WAITING_FOR_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_date)],
            WAITING_FOR_TASKS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_tasks)]
        },
        fallbacks=[CommandHandler('cancel', global_cancel)]
        # CommandHandler('cancel', cancel_command)
    )

    calendar_conv = ConversationHandler(
        entry_points=[
            # CommandHandler("start_calendar", open_format_handler),
            CallbackQueryHandler(open_format_handler, pattern='^calendaractions_')
        ],
        states={
            WAITING_FOR_DATE_C: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_date_calendar)],
            WAITING_FOR_TASKS_C: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_tasks_calendar)],
            WAITING_FOR_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_date_calendar)]
            # WAITING_FOR_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, share_calendar_yes_no)]
        },
        fallbacks=[CommandHandler('cancel', global_cancel)]
    )

    aplication.add_handler(todo_conv)
    aplication.add_handler(calendar_conv)
    aplication.add_handler(CommandHandler("start", start))

    aplication.add_handler(CallbackQueryHandler(button_handler))

    aplication.add_handler(CallbackQueryHandler(debug_any_callback))
    aplication.add_handler(MessageHandler(filters.ALL, debug_any_message))

    logger.info("Bot is starting")
    print("Bot is starting")

    aplication.run_polling(
        drop_pending_updates=True,
        poll_interval=0.5,
        timeout=10
    )

# def save_data():
#     global df

#     df.to_csv('bot_data.csv', index=False, encoding='utf-8')
#     print(df)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("Bot stopped by user")
    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # df.to_csv('bot_data.csv', index=False, encoding='utf-8')
        save_data()
        print('data were saved')
    print("Programm ended")




