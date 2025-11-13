import sys
import os
import json
import wave
import pyaudio
import threading
import re
import time
from openai import OpenAI
import tkinter as tk  # 保留导入，不影响业务逻辑
from tkinter import ttk, messagebox, scrolledtext  # 同上
import requests
import tempfile
from threading import Thread

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QProgressBar,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QFrame, QMessageBox,
    QGridLayout
)
from PyQt5.QtGui import QFont, QIcon, QColor, QPalette
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject

# 导入讯飞语音识别相关库
import websocket
import datetime
import hashlib
import base64
import hmac
from urllib.parse import urlencode
import ssl
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime
import _thread as thread

# 讯飞API配置
APPID = '7c49a8f3'
APISecret = 'OGNjMjA4NTM3OTUwYTlmYzFmOWFiNzA1'
APIKey = 'd697539500dea9c9c3c2645109496aed'

# 音频配置
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
TEMP_AUDIO_FILE = "temp_audio.wav"

STATUS_FIRST_FRAME = 0
STATUS_CONTINUE_FRAME = 1
STATUS_LAST_FRAME = 2

# 全局变量用于存储识别结果
recognition_result = ""
recognition_complete = False
recognition_error = ""

# ------------------- 业务逻辑核心类 -------------------

class TravelPlannerCore:
    def __init__(self):
        # OpenAI 客户端
        self.client = None
        self.model = "claude-3-5-sonnet-latest"
        self.api_base = "https://api.geekai.pro/v1"
        
        # 记录开始时间
        self.start_time = 0
        
        # 示例数据
        self.sample_data = {
            "destination": "日本东京",
            "date": "2024-07-15 至 2024-07-20",
            "budget": "10000",
            "people": "3",
            "preference": "喜欢美食、动漫、带孩子旅行"
        }

    def build_prompt(self, destination, date, budget, people, preference, is_voice_input=False, voice_text=None):
        """构建发送给AI的prompt，根据输入类型使用不同的prompt"""
        if is_voice_input and voice_text:
            # 语音输入专用prompt
            prompt = f"""请根据以下语音输入内容制定详细的旅行计划：

                                语音内容：{voice_text}

                                请提供包含以下内容的详细计划：

                                ## 详细行程安排
                                请按天详细描述每日活动。

                                ## 结构化数据（请严格按照以下格式输出）
                                在计划末尾添加以下结构化数据：
                                '''
                                structured
                                DAY1:
                                '''date:具体日期'''
                                '''city:城市名称'''
                                '''attractions:景点1,景点2,景点3'''
                                '''budget:当日预算'''
                                '''highlights:特色活动描述'''
                                '''food:推荐美食'''
                                DAY2:
                               '''date:具体日期'''
                                '''city:城市名称'''
                                '''attractions:景点1,景点2,景点3'''
                                '''budget:当日预算'''
                                '''highlights:特色活动描述'''
                                '''food:推荐美食'''
                                [继续添加更多天数...]

                                请确保：
                                1. 提供详细的每日行程安排（景点、活动、时间安排）
                                2. 包含交通建议、住宿推荐、餐饮建议
                                3. 提供预算分配建议和实用贴士
                                4. 严格按照上述格式输出结构化数据"""
            return prompt
        else:
            # 文本输入专用prompt
            prompt = f"""请为以下旅行需求制定详细的旅行计划：

                                目的地：{destination}
                                旅行日期：{date}
                                总预算：{budget}元
                                同行人数：{people}人
                                旅行偏好：{preference}

                                请提供包含以下内容的详细计划：

                                ## 详细行程安排
                                请按天详细描述每日活动。

                                ## 结构化数据（请严格按照以下格式输出）
                                在计划末尾添加以下结构化数据：
                                '''
                                structured
                                DAY1:
                                '''date:具体日期'''
                                '''city:城市名称'''
                                '''attractions:景点1,景点2,景点3'''
                                '''budget:当日预算'''
                                '''highlights:特色活动描述'''
                                '''food:推荐美食'''
                                DAY2:
                               '''date:具体日期'''
                                '''city:城市名称'''
                                '''attractions:景点1,景点2,景点3'''
                                '''budget:当日预算'''
                                '''highlights:特色活动描述'''
                                '''food:推荐美食'''
                                [继续添加更多天数...]

                                请确保：
                                1. 提供详细的每日行程安排（景点、活动、时间安排）
                                2. 包含交通建议、住宿推荐、餐饮建议
                                3. 提供预算分配建议和实用贴士
                                4. 严格按照上述格式输出结构化数据"""
            return prompt
    
    def parse_structured_data(self, content):
        """从AI回复中解析结构化数据"""
        structured_data = []
        
        # 查找结构化数据部分
        pattern = r'```structured\s*(.*?)\s*```'
        match = re.search(pattern, content, re.DOTALL)
        
        if not match:
            # 如果没有找到代码块，尝试直接查找DAY模式
            day_pattern = r'DAY(\d+):\s*(.*?)(?=DAY\d+:|$)'
            days = re.findall(day_pattern, content, re.DOTALL)
            
            for day_num, day_content in days:
                day_data = self._parse_day_data(day_content)
                if day_data:
                    day_data['day'] = f'DAY{day_num}'
                    structured_data.append(day_data)
        else:
            # 解析代码块内的数据
            structured_content = match.group(1)
            day_pattern = r'DAY(\d+):(.*?)(?=DAY\d+:|$)'
            days = re.findall(day_pattern, structured_content, re.DOTALL)
            
            for day_num, day_content in days:
                day_data = self._parse_day_data(day_content)
                if day_data:
                    day_data['day'] = f'DAY{day_num}'
                    structured_data.append(day_data)
        
        return structured_data
    
    def _parse_day_data(self, day_content):
        """解析单日数据"""
        data = {}
        
        patterns = {
            'date': r"'''date:([^']*)'''",
            'city': r"'''city:([^']*)'''",
            'attractions': r"'''attractions:([^']*)'''",
            'budget': r"'''budget:([^']*)'''",
            'highlights': r"'''highlights:([^']*)'''",
            'food': r"'''food:([^']*)'''"
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, day_content)
            if match:
                data[key] = match.group(1).strip()
            else:
                data[key] = "未提供"
        return data if data else None
    
    def analyze_budget(self, budget_str, people_str):
        """进行预算分析"""
        try:
            budget = float(budget_str)
            people = int(people_str)
            
            per_person = budget / people
            # 简单估算天数
            days = 5 # 默认5天
            
            analysis = f"""
总预算：{budget:,.0f}元
人均预算：{per_person:,.0f}元
每日预算：{budget/days:,.0f}元

预算分配建议：
- 交通费用：{budget*0.3:,.0f}元 (30%)
- 住宿费用：{budget*0.4:,.0f}元 (40%)
- 餐饮费用：{budget*0.2:,.0f}元 (20%)
- 景点门票：{budget*0.1:,.0f}元 (10%)

预算提醒：请根据实际情况调整各项费用比例。"""
            
            return analysis
            
        except ValueError:
            return "预算分析：请输入有效的数字格式"
    
    def validate_inputs(self, destination, date, budget, people, preference, is_voice_input=False):
        """验证输入数据，语音输入不需要验证这些字段"""
        if is_voice_input:
            return True, "语音输入验证通过"
            
        if not all([destination, date, budget, people, preference]):
            return False, "所有字段均为必填项"
        
        try:
            budget_val = float(budget)
            people_val = int(people)
            
            if budget_val <= 0 or people_val <= 0:
                return False, "预算和人数必须大于0"
                
        except ValueError:
            return False, "预算必须为数字，人数必须为整数"
        
        return True, "验证通过"

    def generate_plan_thread(self, api_key, api_base, destination, date, budget, people, preference, 
                            callback_func, is_voice_input=False, voice_text=None):
        """
        在后台线程中生成旅行计划的核心逻辑。
        执行完毕后，通过 callback_func 将结果返回给主线程。
        """
        error_msg = None
        plan_content = None
        structured_data = None
        
        try:
            self.client = OpenAI(
                api_key=api_key,
                base_url=api_base
            )
            
            prompt = self.build_prompt(
                destination, date, budget, people, preference, 
                is_voice_input, voice_text
            )
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": """你是一个专业的旅行规划师，擅长制定详细、实用的旅行计划。
                                                        请严格按照指定的格式输出，包含详细的每日行程和结构化数据。"""},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=20000,
                temperature=0.7
            )
            
            plan_content = response.choices[0].message.content
            
            # 解析结构化数据
            structured_data = self.parse_structured_data(plan_content)
            
        except Exception as e:
            error_msg = f"生成旅行计划时出错: {str(e)}"
        
        finally:
            # 无论成功失败，都调用回调函数通知UI线程
            callback_func(plan_content, structured_data, error_msg)

# ------------------- 语音识别相关类 -------------------

class AudioRecorder(QThread):
    """音频录制线程"""
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.is_recording = False
        self.frames = []

    def run(self):
        """录音主逻辑"""
        try:
            p = pyaudio.PyAudio()

            stream = p.open(format=FORMAT,
                            channels=CHANNELS,
                            rate=RATE,
                            input=True,
                            frames_per_buffer=CHUNK)

            self.frames = []
            self.is_recording = True

            while self.is_recording:
                data = stream.read(CHUNK, exception_on_overflow=False)
                self.frames.append(data)

            stream.stop_stream()
            stream.close()
            p.terminate()

            # 保存音频文件
            self.save_audio()
            self.finished.emit()

        except Exception as e:
            self.error.emit(f"录音错误: {str(e)}")

    def stop_recording(self):
        """停止录音"""
        self.is_recording = False

    def save_audio(self):
        """保存音频为WAV文件"""
        wf = wave.open(TEMP_AUDIO_FILE, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(pyaudio.PyAudio().get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(self.frames))
        wf.close()


class Ws_Param(object):
    """WebSocket参数类"""

    def __init__(self, APPID, APIKey, APISecret, AudioFile):
        self.APPID = APPID
        self.APIKey = APIKey
        self.APISecret = APISecret
        self.AudioFile = AudioFile

        # 公共参数(common)
        self.CommonArgs = {"app_id": self.APPID}
        # 业务参数(business)
        self.BusinessArgs = {"domain": "iat", "language": "zh_cn", "accent": "mandarin", "vinfo": 1, "vad_eos": 10000}

    def create_url(self):
        url = 'wss://ws-api.xfyun.cn/v2/iat'
        # 生成RFC1123格式的时间戳
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        # 拼接字符串
        signature_origin = "host: " + "ws-api.xfyun.cn" + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + "/v2/iat " + "HTTP/1.1"
        # 进行hmac-sha256进行加密
        signature_sha = hmac.new(self.APISecret.encode('utf-8'), signature_origin.encode('utf-8'),
                                 digestmod=hashlib.sha256).digest()
        signature_sha = base64.b64encode(signature_sha).decode(encoding='utf-8')

        authorization_origin = "api_key=\"%s\", algorithm=\"%s\", headers=\"%s\", signature=\"%s\"" % (
            self.APIKey, "hmac-sha256", "host date request-line", signature_sha)
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')
        # 将请求的鉴权参数组合为字典
        v = {
            "authorization": authorization,
            "date": date,
            "host": "ws-api.xfyun.cn"
        }
        # 拼接鉴权参数，生成url
        url = url + '?' + urlencode(v)
        return url


# 回调函数
def on_message(ws, message):
    global recognition_result, recognition_error
    try:
        code = json.loads(message)["code"]
        sid = json.loads(message)["sid"]
        if code != 0:
            errMsg = json.loads(message)["message"]
            recognition_error = "sid:%s call error:%s code is:%s" % (sid, errMsg, code)
            print(recognition_error)
        else:
            data = json.loads(message)["data"]["result"]["ws"]
            result = ""
            for i in data:
                for w in i["cw"]:
                    result += w["w"]
            recognition_result += result  # 累积结果
            print("sid:%s call success!,data is:%s" % (sid, json.dumps(data, ensure_ascii=False)))
    except Exception as e:
        recognition_error = f"receive msg,but parse exception: {e}"
        print(recognition_error)


def on_error(ws, error):
    global recognition_error
    recognition_error = f"### error: {error}"
    print(recognition_error)


def on_close(ws, a, b):
    global recognition_complete
    recognition_complete = True
    print("### closed ###")


def on_open(ws):
    def run(*args):
        frameSize = 8000  # 每一帧的音频大小
        intervel = 0.04  # 发送音频间隔(单位:s)
        status = STATUS_FIRST_FRAME  # 音频的状态信息，标识音频是第一帧，还是中间帧、最后一帧

        # 使用全局wsParam
        with open(wsParam.AudioFile, "rb") as fp:
            while True:
                buf = fp.read(frameSize)
                # 文件结束
                if not buf:
                    status = STATUS_LAST_FRAME
                # 第一帧处理
                # 发送第一帧音频，带business 参数
                # appid 必须带上，只需第一帧发送
                if status == STATUS_FIRST_FRAME:
                    d = {"common": wsParam.CommonArgs,
                         "business": wsParam.BusinessArgs,
                         "data": {"status": 0, "format": "audio/L16;rate=16000",
                                  "audio": str(base64.b64encode(buf), 'utf-8'),
                                  "encoding": "raw"}}
                    d = json.dumps(d)
                    ws.send(d)
                    status = STATUS_CONTINUE_FRAME
                # 中间帧处理
                elif status == STATUS_CONTINUE_FRAME:
                    d = {"data": {"status": 1, "format": "audio/L16;rate=16000",
                                  "audio": str(base64.b64encode(buf), 'utf-8'),
                                  "encoding": "raw"}}
                    ws.send(json.dumps(d))
                # 最后一帧处理
                elif status == STATUS_LAST_FRAME:
                    d = {"data": {"status": 2, "format": "audio/L16;rate=16000",
                                  "audio": str(base64.b64encode(buf), 'utf-8'),
                                  "encoding": "raw"}}
                    ws.send(json.dumps(d))
                    time.sleep(1)
                    break
                # 模拟音频采样间隔
                time.sleep(intervel)
        ws.close()

    thread.start_new_thread(run, ())


# 全局wsParam变量
wsParam = None


class SpeechRecognizer(QThread):
    """语音识别线程"""
    result_ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self):
        super().__init__()

    def run(self):
        """执行语音识别"""
        global recognition_result, recognition_complete, recognition_error, wsParam

        # 重置全局变量
        recognition_result = ""
        recognition_complete = False
        recognition_error = ""

        try:
            # 检查音频文件是否存在
            if not os.path.exists(TEMP_AUDIO_FILE):
                self.error.emit("音频文件不存在，请先录音")
                return

            # 创建WebSocket参数
            wsParam = Ws_Param(APPID=APPID, APISecret=APISecret,
                               APIKey=APIKey,
                               AudioFile=TEMP_AUDIO_FILE)

            websocket.enableTrace(False)
            wsUrl = wsParam.create_url()

            # 创建WebSocket连接
            ws = websocket.WebSocketApp(wsUrl, on_message=on_message, on_error=on_error, on_close=on_close)
            ws.on_open = on_open

            # 运行WebSocket
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

            # 检查结果
            if recognition_error:
                self.error.emit(recognition_error)
            elif recognition_result:
                self.result_ready.emit(recognition_result)
            else:
                self.error.emit("识别结果为空")

        except Exception as e:
            self.error.emit(f"识别错误: {str(e)}")

# ------------------- 工作线程类 -------------------

class Worker(QObject):
    finished = pyqtSignal(object, object, object) # plan_content, structured_data, error_msg

    def __init__(self, core, api_key, api_base, destination, date, budget, people, preference, 
                 is_voice_input=False, voice_text=None):
        super().__init__()
        self.core = core
        self.api_key = api_key
        self.api_base = api_base
        self.destination = destination
        self.date = date
        self.budget = budget
        self.people = people
        self.preference = preference
        self.is_voice_input = is_voice_input
        self.voice_text = voice_text

    def run(self):
        # 调用核心逻辑
        self.core.generate_plan_thread(
            self.api_key, self.api_base, self.destination, self.date,
            self.budget, self.people, self.preference, self.finished.emit,
            self.is_voice_input, self.voice_text
        )

# ------------------- 语音识别窗口 -------------------

class SpeechRecognitionWindow(QMainWindow):
    """语音识别窗口"""
    recognition_done = pyqtSignal(str)  # 识别完成信号，传递识别文本
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.recorder = None
        self.recognizer = None
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("语音输入 - 旅行规划")
        self.setGeometry(200, 200, 600, 500)

        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 创建布局
        layout = QVBoxLayout()

        # 标题
        title = QLabel("请说出您的旅行需求")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        layout.addWidget(title)

        # 状态标签
        self.status_label = QLabel("准备就绪")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("QLabel { background-color: #f0f0f0; padding: 10px; }")
        layout.addWidget(self.status_label)

        # 按钮布局
        button_layout = QHBoxLayout()

        self.record_btn = QPushButton("开始录音")
        self.record_btn.clicked.connect(self.start_recording)
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 10px;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        button_layout.addWidget(self.record_btn)

        self.stop_btn = QPushButton("停止录音")
        self.stop_btn.clicked.connect(self.stop_recording)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                padding: 10px;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        button_layout.addWidget(self.stop_btn)

        self.recognize_btn = QPushButton("开始识别")
        self.recognize_btn.clicked.connect(self.start_recognition)
        self.recognize_btn.setEnabled(False)
        self.recognize_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 10px;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #0b7dda;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        button_layout.addWidget(self.recognize_btn)

        layout.addLayout(button_layout)

        # 结果显示区域
        result_label = QLabel("识别结果：")
        result_label.setFont(QFont("Microsoft YaHei", 12))
        layout.addWidget(result_label)

        self.result_text = QTextEdit()
        self.result_text.setFont(QFont("Microsoft YaHei", 11))
        self.result_text.setReadOnly(True)
        layout.addWidget(self.result_text)

        # 调试信息显示区域
        debug_label = QLabel("调试信息：")
        debug_label.setFont(QFont("Microsoft YaHei", 10))
        layout.addWidget(debug_label)

        self.debug_text = QTextEdit()
        self.debug_text.setFont(QFont("Consolas", 9))
        self.debug_text.setReadOnly(True)
        self.debug_text.setMaximumHeight(100)
        layout.addWidget(self.debug_text)

        central_widget.setLayout(layout)
        
    def start_recording(self):
        """开始录音"""
        self.recorder = AudioRecorder()
        self.recorder.finished.connect(self.on_recording_finished)
        self.recorder.error.connect(self.on_error)
        self.recorder.start()

        self.status_label.setText("正在录音...")
        self.status_label.setStyleSheet("QLabel { background-color: #ffcccc; padding: 10px; }")
        self.record_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.recognize_btn.setEnabled(False)
        self.result_text.clear()
        self.debug_text.clear()

    def stop_recording(self):
        """停止录音"""
        if self.recorder:
            self.recorder.stop_recording()
            self.status_label.setText("正在保存音频...")
            self.stop_btn.setEnabled(False)

    def on_recording_finished(self):
        """录音完成"""
        self.status_label.setText("录音完成，可以开始识别")
        self.status_label.setStyleSheet("QLabel { background-color: #ccffcc; padding: 10px; }")
        self.record_btn.setEnabled(True)
        self.recognize_btn.setEnabled(True)

    def start_recognition(self):
        """开始识别"""
        self.recognizer = SpeechRecognizer()
        self.recognizer.result_ready.connect(self.on_recognition_result)
        self.recognizer.error.connect(self.on_error)
        self.recognizer.start()

        self.status_label.setText("正在识别...")
        self.status_label.setStyleSheet("QLabel { background-color: #ffffcc; padding: 10px; }")
        self.recognize_btn.setEnabled(False)
        self.debug_text.append("开始语音识别...")

    def on_recognition_result(self, text):
        """显示识别结果并返回主窗口"""
        self.result_text.setText(text)
        self.status_label.setText("识别完成，即将返回主界面")
        self.status_label.setStyleSheet("QLabel { background-color: #ccffcc; padding: 10px; }")
        
        # 发送信号并关闭窗口
        self.recognition_done.emit(text)
        self.close()

    def on_error(self, error_msg):
        """处理错误"""
        QMessageBox.critical(self, "错误", error_msg)
        self.status_label.setText("发生错误")
        self.status_label.setStyleSheet("QLabel { background-color: #ffcccc; padding: 10px; }")
        self.record_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.recognize_btn.setEnabled(os.path.exists(TEMP_AUDIO_FILE))
        self.debug_text.append(f"错误: {error_msg}")

# ------------------- 主窗口 -------------------

class TravelPlannerQt(QMainWindow):
    def __init__(self):
        super().__init__()
        self.core = TravelPlannerCore()  # 实例化业务逻辑核心
        self.voice_text = ""  # 存储语音识别结果
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("智能旅行规划工具")
        self.setGeometry(100, 100, 1100, 850)

        # 设置整体样式
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f2f5;
            }
            QFrame {
                background-color: #ffffff;
                border-radius: 10px;
                border: 1px solid #e0e0e0;
            }
            QLabel {
                color: #87CEEB; /* 浅天蓝色 */
                font-family: 'Microsoft YaHei', 'SimHei', sans-serif;
            }
            QLineEdit, QTextEdit {
                padding: 10px;
                border: 1px solid #cccccc;
                border-radius: 5px;
                background-color: #f9f9f9;
                font-size: 14px;
                color: #333333;
                font-family: 'Microsoft YaHei', 'SimHei', sans-serif;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #66afe9;
            }
            QPushButton {
                background-color: #5a9bd5;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                font-family: 'Microsoft YaHei', 'SimHei', sans-serif;
            }
            QPushButton:hover {
                background-color: #4a8ac8;
            }
            QPushButton:disabled {
                background-color: #c0c0c0;
            }
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 5px;
                background-color: #f0f0f0;
            }
            QProgressBar::chunk {
                background-color: #5a9bd5;
                border-radius: 4px;
            }
            QTabWidget::pane {
                border: 1px solid #e0e0e0;
                border-radius: 10px;
                top: -1px;
            }
            QTabBar::tab {
                background: #f0f0f0;
                border: 1px solid #e0e0e0;
                border-bottom-color: #e0e0e0;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                min-width: 8ex;
                padding: 10px 20px;
                font-size: 14px;
                color: #333333;
                font-family: 'Microsoft YaHei', 'SimHei', sans-serif;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                border-bottom-color: #ffffff; /* 和pane颜色一致，实现融合效果 */
                font-weight: bold;
                color: #5a9bd5;
            }
            QTreeWidget {
                border: 1px solid #e0e0e0;
                border-radius: 5px;
                color: #333333;
                font-family: 'Microsoft YaHei', 'SimHei', sans-serif;
            }
            QTreeWidget::item {
                padding: 5px;
            }
            QTreeWidget::item:selected {
                background-color: #e6f7ff;
                color: #5a9bd5;
            }
            QHeaderView::section {
                background-color: #f5f5f5;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #e0e0e0;
                font-weight: bold;
                color: #333333;
            }
        """)


        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(4,4,4,4)
        main_layout.setSpacing(5)

        # 标题
        title_label = QLabel("🌍 智能旅行规划工具")
        title_label.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: #2c3e50; margin-bottom: 4px;")
        main_layout.addWidget(title_label)

        # API配置区域
        api_frame = QFrame()
        api_layout = QVBoxLayout(api_frame)
        api_layout.setContentsMargins(1,1,1,1)
        api_layout.setSpacing(4)

        api_title = QLabel("API配置")
        api_title.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        api_title.setStyleSheet("color: #34495e; border-bottom: 2px solid #5a9bd5; padding-bottom: 5px;")
        api_layout.addWidget(api_title)

        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(1, 1, 1, 1) 
        row_layout.setSpacing(1)
        label = QLabel("API密钥:")
        label.setFont(QFont("Microsoft YaHei", 12))
        self.api_entry = QLineEdit()
        self.api_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_entry.setFixedHeight(40) 
        row_layout.addWidget(label, 1)
        row_layout.addWidget(self.api_entry, 4)
        api_layout.addLayout(row_layout)

        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(1, 1, 1, 1) 
        row_layout.setSpacing(1)
        label = QLabel("API基础URL:")
        label.setFont(QFont("Microsoft YaHei", 12))
        self.api_base_entry = QLineEdit(self.core.api_base) 
        self.api_base_entry.setFixedHeight(40)  # 设置 api_base 为默认值
        row_layout.addWidget(label, 1)
        row_layout.addWidget(self.api_base_entry, 4)
        api_layout.addLayout(row_layout)

        main_layout.addWidget(api_frame)

        # 语音输入区域
        voice_frame = QFrame()
        voice_layout = QHBoxLayout(voice_frame)
        voice_layout.setContentsMargins(4, 4, 4, 4)
        voice_layout.setSpacing(5)

        voice_label = QLabel("语音输入内容:")
        voice_label.setFont(QFont("Microsoft YaHei", 12))
        self.voice_entry = QLineEdit()
        self.voice_entry.setFixedHeight(40)
        self.voice_entry.setReadOnly(True)  # 语音输入内容只读
        self.voice_button = QPushButton("语音输入（可选输入）")
        self.voice_button.clicked.connect(self.open_voice_recognition)
        self.voice_button.setFixedHeight(40)
        
        voice_layout.addWidget(voice_label, 1)
        voice_layout.addWidget(self.voice_entry, 3)
        voice_layout.addWidget(self.voice_button, 1)
        
        main_layout.addWidget(voice_frame)

        # 旅行信息输入区域
        info_frame = QFrame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(4,4,4,4)
        info_layout.setSpacing(3)

        info_title = QLabel("旅行信息（默认输入）")
        info_title.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        info_title.setStyleSheet("color: #34495e; border-bottom: 2px solid #5a9bd5; padding-bottom: 5px;")
        info_layout.addWidget(info_title)
        
        # 使用网格布局来排列输入项，更整齐
        grid_layout = QGridLayout()
        grid_layout.setSpacing(5)
        grid_layout.setColumnStretch(1, 1)  # 让输入框列拉伸

        labels = ["目的地:", "旅行日期:", "预算(元):", "同行人数:", "旅行偏好:"]
        self.input_entries = {}

        for i, text in enumerate(labels):
            label = QLabel(text)
            label.setFont(QFont("Microsoft YaHei", 12))
            entry = QLineEdit()
            entry.setFixedHeight(40)
            self.input_entries[text.strip(':')] = entry
            grid_layout.addWidget(label, i, 0)
            grid_layout.addWidget(entry, i, 1)

        # 设置 sample_data 为默认值
        self.input_entries["目的地"].setText(self.core.sample_data["destination"])
        self.input_entries["旅行日期"].setText(self.core.sample_data["date"])
        self.input_entries["预算(元)"].setText(self.core.sample_data["budget"])
        self.input_entries["同行人数"].setText(self.core.sample_data["people"])
        self.input_entries["旅行偏好"].setText(self.core.sample_data["preference"])

        info_layout.addLayout(grid_layout)
        main_layout.addWidget(info_frame)

        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        button_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.generate_btn = QPushButton("生成旅行计划")
        self.generate_btn.clicked.connect(self.generate_plan)
        self.clear_btn = QPushButton("清空所有")
        self.clear_btn.clicked.connect(self.clear_inputs)
        button_layout.addWidget(self.generate_btn)
        button_layout.addWidget(self.clear_btn)
        main_layout.addLayout(button_layout)

        # 进度条和状态提示
        status_layout = QHBoxLayout()
        status_layout.setSpacing(5)
        self.status_label = QLabel("就绪")
        self.status_label.setFont(QFont("Microsoft YaHei", 12))
        self.progress = QProgressBar()
        self.progress.setVisible(False)  # 默认隐藏
        status_layout.addWidget(self.progress, 1)  # 进度条拉伸
        status_layout.addWidget(self.status_label)
        main_layout.addLayout(status_layout)

        # 创建左右分栏的TabWidget
        self.notebook = QTabWidget()
        
        # 详细计划标签页
        plan_widget = QWidget()
        plan_layout = QVBoxLayout(plan_widget)
        plan_layout.setContentsMargins(2,2,2,2)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setFont(QFont("Microsoft YaHei", 11))
        plan_layout.addWidget(self.result_text)
        self.notebook.addTab(plan_widget, "详细旅行计划")

        # 行程概览标签页
        overview_widget = QWidget()
        overview_layout = QVBoxLayout(overview_widget)
        overview_layout.setContentsMargins(4,4,4,4)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(['日期', '城市/地区', '主要景点', '当日预算', '特色信息'])
        # 设置列宽
        self.tree.setColumnWidth(0, 150)
        self.tree.setColumnWidth(1, 120)
        self.tree.setColumnWidth(2, 200)
        self.tree.setColumnWidth(3, 100)
        self.tree.setColumnWidth(4, 250)
        overview_layout.addWidget(self.tree)
        self.notebook.addTab(overview_widget, "行程概览")

        main_layout.addWidget(self.notebook, 1)  # 让TabWidget占据大部分空间

    def open_voice_recognition(self):
        """打开语音识别窗口"""
        self.voice_window = SpeechRecognitionWindow(self)
        self.voice_window.recognition_done.connect(self.on_voice_recognition_done)
        self.voice_window.show()
        
    def on_voice_recognition_done(self, text):
        """处理语音识别结果"""
        self.voice_text = text
        self.voice_entry.setText(text)
        QMessageBox.information(self, "识别完成", "语音识别已完成，您可以点击生成旅行计划按钮")

    def generate_plan(self):
        """生成旅行计划的入口，在主线程中执行"""
        # 检查是否使用语音输入
        is_voice_input = bool(self.voice_text.strip())
        
        if is_voice_input:
            # 语音输入模式
            destination = ""
            date = ""
            budget = ""
            people = ""
            preference = ""
            
            # 验证语音输入
            is_valid, msg = self.core.validate_inputs(destination, date, budget, people, preference, is_voice_input)
            if not is_valid:
                QMessageBox.warning(self, "输入错误", msg)
                return
        else:
            # 文本输入模式
            destination = self.input_entries["目的地"].text().strip()
            date = self.input_entries["旅行日期"].text().strip()
            budget = self.input_entries["预算(元)"].text().strip()
            people = self.input_entries["同行人数"].text().strip()
            preference = self.input_entries["旅行偏好"].text().strip()

            # 验证文本输入
            is_valid, msg = self.core.validate_inputs(destination, date, budget, people, preference)
            if not is_valid:
                QMessageBox.warning(self, "输入错误", msg)
                return
        
        # 检查API密钥
        api_key = self.api_entry.text().strip()
        if not api_key:
            QMessageBox.warning(self, "错误", "请输入API密钥")
            return
        
        api_base = self.api_base_entry.text().strip()
        
        # UI状态更新
        self.generate_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)  # 不确定进度
        self.status_label.setText("AI正在思考中...")
        self.result_text.clear()
        self.tree.clear()

        # 创建并启动线程
        self.thread = QThread()
        self.worker = Worker(
            self.core, api_key, api_base, destination, date, budget, people, preference,
            is_voice_input, self.voice_text
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._update_result)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _update_result(self, plan_content, structured_data, error_msg):
        """在主线程中更新结果显示 (由信号触发)"""
        # 恢复UI状态
        self.generate_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status_label.setText("就绪")
        
        if error_msg:
            QMessageBox.critical(self, "错误", error_msg)
            return
        
        # 显示详细旅行计划
        self.result_text.setText(plan_content)
        
        # 添加预算分析（仅文本输入时）
        if not self.voice_text.strip():
            budget_str = self.input_entries["预算(元)"].text().strip()
            people_str = self.input_entries["同行人数"].text().strip()
            budget_analysis = self.core.analyze_budget(budget_str, people_str)
            self.result_text.append(f"\n\n💰 预算分析:\n{budget_analysis}")
        
        # 更新树形视图
        self._update_treeview(structured_data)

    def _update_treeview(self, structured_data):
        """更新树形视图显示行程概览"""
        self.tree.clear()
        
        if not structured_data:
            QTreeWidgetItem(self.tree, ['无结构化数据', '', '', '', ''])
            return
        
        for day_data in structured_data:
            day_text = f"{day_data.get('day', '')} - {day_data.get('date', '')}"
            attractions = day_data.get('attractions', '未提供').replace(',', '\n')
            highlights = day_data.get('highlights', '未提供')
            food = day_data.get('food', '未提供')
            
            highlights_text = f"特色: {highlights}\n美食: {food}"
            
            item = QTreeWidgetItem([
                day_text,
                day_data.get('city', '未提供'),
                attractions,
                day_data.get('budget', '未提供'),
                highlights_text
            ])
            self.tree.addTopLevelItem(item)

    def clear_inputs(self):
        """清空所有输入"""
        for entry in self.input_entries.values():
            entry.clear()
        self.api_entry.clear()
        self.api_base_entry.setText(self.core.api_base)  # 清空后恢复默认 api_base
        self.voice_entry.clear()
        self.voice_text = ""
        self.result_text.clear()
        self.tree.clear()
        self.status_label.setText("就绪")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TravelPlannerQt()
    window.show()
    sys.exit(app.exec())

