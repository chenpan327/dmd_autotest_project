import serial
import serial.tools.list_ports
import time
from threading import Thread, Lock


class SerialPort:
    """Serial communication class, supporting basic serial operations and thread-safe data reception"""

    def __init__(self, port=None, baudrate=115200, timeout=0.1):
        """
        Initialize the serial port object

        Parameters:
            port: Serial port name, e.g. 'COM3' or '/dev/ttyUSB0'. Automatically finds the first available port by default
            baudrate: Baud rate, default 115200
            timeout: Read timeout in seconds, default 0.1 seconds
        """
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
        """Find and return all available serial port names"""
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]

    def connect(self):
        """Connect to the serial port"""
        try:
            # Automatically select the first available port if not specified
            if not self.port:
                available_ports = self.find_available_ports()
                if not available_ports:
                    raise Exception("No available serial ports found")
                self.port = available_ports[0]
                print("Automatically selected serial port: {}".format(self.port))

            # Initialize serial port
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_1,
                bytesize=serial.EIGHTBITS
            )

            if self.ser.is_open:
                self.is_connected = True
                # Start receive thread
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
        """Background data reception thread"""
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
        """
        Send data

        Parameters:
            data: Data to send, string or bytes
            is_hex: Whether to send in hexadecimal format, default False
        """
        if not self.is_connected:
            print("Serial port not connected, cannot send data")
            return False

        try:
            if is_hex:
                # Send in hexadecimal format, need to convert string to bytes first
                data = bytes.fromhex(data)
            elif isinstance(data, str):
                # Convert string to bytes
                data = data.encode('utf-8')

            self.ser.write(data)
            return True
        except Exception as e:
            print("Failed to send data: {}".format(str(e)))
            return False

    def read_data(self, length=None, timeout=None):
        """
        Read data from buffer

        Parameters:
            length: Number of bytes to read, None means read all
            timeout: Timeout in seconds, None uses default timeout

        Returns:
            Read byte data
        """
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

            # Check timeout
            if timeout is not None and (time.time() - start_time) >= timeout:
                return b""

            time.sleep(0.001)

    def read_line(self, end=b'\n', timeout=None):
        """
        Read data line by line (until the end character is encountered)

        Parameters:
            end: Line terminator, default newline character
            timeout: Timeout in seconds

        Returns:
            Read line data, including terminator
        """
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

            # Check timeout
            if timeout is not None and (time.time() - start_time) >= timeout:
                return b""

            time.sleep(0.001)

    def clear_buffer(self):
        """Clear receive buffer"""
        with self.buffer_lock:
            self.receive_buffer = b""
        if self.ser:
            self.ser.flushInput()
            self.ser.flushOutput()

    def disconnect(self):
        """Disconnect from serial port"""
        self.running = False
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)

        if self.ser and self.ser.is_open:
            self.ser.close()

        self.is_connected = False
        self.port = None
        print("Serial port disconnected")

    def __del__(self):
        """Ensure disconnection when object is destroyed"""
        self.disconnect()


# Usage example
if __name__ == "__main__":
    # Create serial port object
    serial_port = SerialPort(baudrate=115200)

    # Connect to serial port
    if serial_port.connect():
        try:
            # Send test data
            serial_port.send_data("Hello, Serial!")
            print("Sent data: Hello, Serial!")

            # Example of sending hexadecimal data
            # serial_port.send_data("A5 01 02", is_hex=True)

            # Loop to receive data
            while True:
                data = serial_port.read_line(timeout=1)
                if data:
                    try:
                        # Try to decode as string
                        print("Received data: {}".format(data.decode('utf-8')))
                    except UnicodeDecodeError:
                        # Display in hexadecimal if decoding fails
                        print("Received data (hex): {}".format(data.hex(' ')))

                time.sleep(0.1)

        except KeyboardInterrupt:
            print("User interrupted")
        finally:
            serial_port.disconnect()