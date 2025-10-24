import serial
import serial.tools.list_ports
import time
from threading import Thread, Lock


class SerialPort:
    """Serial communication class, supporting basic serial operations and thread-safe data reception"""

    def __init__(self, port=None, baudrate=115200, timeout=0.1):
        self.ser = None
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.is_connected = False
        self.receive_buffer = b""  # Receive buffer
        self.buffer_lock = Lock()  # Buffer thread lock
        self.receive_thread = None
        self.running = False  # Receive thread running flag

    def find_available_ports(self):
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]

    def connect(self):
        try:
            if not self.port:
                available_ports = self.find_available_ports()
                if not available_ports:
                    raise Exception("No available serial ports found")
                self.port = available_ports[0]
                print("Automatically selected serial port: {}".format(self.port))

            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                parity=serial.serialutil.PARITY_NONE,
                stopbits=1,
                bytesize=serial.serialutil.EIGHTBITS
            )

            if self.ser.is_open:
                self.is_connected = True
                self.running = True
                self.receive_thread = Thread(target=self._receive_data, daemon=True)
                self.receive_thread.start()
                print("Serial port {} connected successfully, baudrate: {}".format(self.port, self.baudrate))
                return True
            return False

        except Exception as e:
            print("Serial port connection failed: {}".format(str(e)))
            self.is_connected = False
            return False

    def _receive_data(self):
        while self.running and self.is_connected:
            try:
                if self.ser.in_waiting:
                    data = self.ser.read(self.ser.in_waiting)
                    with self.buffer_lock:
                        self.receive_buffer += data
            except Exception as e:
                print("Error receiving data: {}".format(str(e)))
                time.sleep(0.1)

    def send_data(self, data, is_hex=False):
        if not self.is_connected:
            print("Serial port not connected, cannot send data")
            return False

        try:
            if is_hex:
                data = bytes.fromhex(data)
            elif isinstance(data, str):
                data = data.encode('utf-8')

            self.ser.write(data)
            return True
        except Exception as e:
            print("Failed to send data: {}".format(str(e)))
            return False

    def read_data(self, length=None, timeout=None):
        if not self.is_connected:
            return b""

        start_time = time.time()
        while True:
            with self.buffer_lock:
                if length is None:
                    if self.receive_buffer:
                        data = self.receive_buffer
                        self.receive_buffer = b""
                        return data
                else:
                    if len(self.receive_buffer) >= length:
                        data = self.receive_buffer[:length]
                        self.receive_buffer = self.receive_buffer[length:]
                        return data

            if timeout is not None and (time.time() - start_time) >= timeout:
                return b""

            time.sleep(0.001)

    def read_line(self, end=b'\n', timeout=None):
        if not self.is_connected:
            return b""

        start_time = time.time()
        while True:
            with self.buffer_lock:
                end_idx = self.receive_buffer.find(end)
                if end_idx != -1:
                    line = self.receive_buffer[:end_idx + len(end)]
                    self.receive_buffer = self.receive_buffer[end_idx + len(end):]
                    return line

            if timeout is not None and (time.time() - start_time) >= timeout:
                return b""

            time.sleep(0.001)

    def clear_buffer(self):
        with self.buffer_lock:
            self.receive_buffer = b""
        if self.ser:
            self.ser.flushInput()
            self.ser.flushOutput()

    def disconnect(self):
        self.running = False
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)

        if self.ser and self.ser.is_open:
            self.ser.close()

        self.is_connected = False
        self.port = None
        print("Serial port disconnected")

    def __del__(self):
        self.disconnect()