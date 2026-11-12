
import serial
import serial.tools.list_ports

from collections.abc import Callable
from typing import Any
import threading
import time

class dav_serial_driver_t():

    def __init__(self,
    close_callback : str | Callable[[],Any] = "print('serial close')",
    list_update_callback : str | Callable[[],Any] = "print('serial list update')") -> None:

        self.serial_close_callback = close_callback
        self.serial_list_update_callback = list_update_callback

        self.thread_exit_flag = 0

        self.com_state = 0
        self.open_com_port = None
        self.com_ser = None

        self.usb_com_port_list = []
        self.usb_com_name_list = []

        self.baud = 921600

        self.serial_thread = threading.Thread(target=self.serial_update_task)
        self.serial_thread.start()

    def __del__(self):
        self.thread_exit_flag = 1

        if self.com_state:
            self.com_state = 0
            self.com_ser.close()

        self.open_com_port = None
        self.com_ser = None

        if self.serial_thread != None:
            self.serial_thread.join()

        print('serial task destory')

    def close_del_serial(self):
        self.thread_exit_flag = 1

        if self.com_state:
            self.com_state = 0
            self.com_ser.close()

        if self.serial_thread != None:
            self.serial_thread.join()

        self.open_com_port = None
        self.com_ser = None

        self.usb_com_port_list = []
        self.usb_com_name_list = []

        self.serial_thread = None

        return

    def open_serial(self, index, baud):
        if index >= len(self.usb_com_port_list):
            return False

        self.baud = baud

        try:
            self.com_ser = serial.Serial(self.usb_com_port_list[index], baud, timeout = 5)
            self.open_com_port = self.usb_com_port_list[index]
            self.com_state = 1
            return True

        except serial.serialutil.SerialException as e:
            print(f'Port is already in use: {e}')
        except ValueError as e:
            print(f'Invalid parameter: {e}')
        except OSError as e:
            print(f'Error occurred when opening the port: {e}')

        return False

    def close_serial(self):

        if self.com_state != 0:
            self.com_state = 0
            self.open_com_port = None
            if self.com_ser != None and self.com_ser.isOpen():
                self.com_ser.close()
                self.com_ser = None

            if isinstance(self.serial_close_callback, str):
                exec(self.serial_close_callback)
            elif callable(self.serial_close_callback):
                self.serial_close_callback()
            return True
        else:
            False

    def serial_write_data(self, send_data):
        if len(send_data) == 0:
            return
        if self.com_state == 1:
            try:
                self.com_ser.write(send_data)
                self.com_ser.flush()
            except Exception as e:
                if self.com_state == 1:
                    self.com_state = 2
                return
        return

    def serial_read_data(self):
        if  self.com_state == 1:
            try:
                return self.com_ser.read_all()
            except Exception as e:
                if self.com_state == 1:
                    self.com_state = 2
                return b''
        else:
            return b''

    def serial_update_task(self):
        temp = list(serial.tools.list_ports.comports())

        self.usb_com_port_list = []
        self.usb_com_name_list = []

        if len(temp):
            for i in temp:
                self.usb_com_port_list.append(i[0])
                self.usb_com_name_list.append(i[1])
            if isinstance(self.serial_list_update_callback, str):
                exec(self.serial_list_update_callback)
            elif callable(self.serial_list_update_callback):
                self.serial_list_update_callback()

        while self.thread_exit_flag == 0:

            if self.com_state == 0:

                temp = list(serial.tools.list_ports.comports())
                if len(temp) == 0:
                    if len(self.usb_com_name_list) != 0:
                        self.usb_com_port_list = []
                        self.usb_com_name_list = []
                        if isinstance(self.serial_list_update_callback, str):
                            exec(self.serial_list_update_callback)
                        elif callable(self.serial_list_update_callback):
                            self.serial_list_update_callback()

                    time.sleep(1)
                    continue

                change_flag = 0

                temp_port_list = []

                temp_name_list = []

                for i in temp:
                    temp_port_list.append(i[0])
                    temp_name_list.append(i[1])
                    if i[1] not in self.usb_com_name_list:
                        change_flag = 1

                i = 0
                while i < len(self.usb_com_name_list):
                    if self.usb_com_name_list[i] not in temp_name_list:
                        change_flag = 1
                    i+=1

                if change_flag:
                    self.usb_com_port_list = temp_port_list
                    self.usb_com_name_list = temp_name_list
                    if isinstance(self.serial_list_update_callback, str):
                        exec(self.serial_list_update_callback)
                    elif callable(self.serial_list_update_callback):
                        self.serial_list_update_callback()

                time.sleep(0.5)

            elif self.com_state == 1:
                temp = list(serial.tools.list_ports.comports())
                if len(temp) == 0:
                    self.com_state = 2
                else:
                    temp_port_list = []

                    for i in temp:
                        temp_port_list.append(i[0])

                    if self.open_com_port not in temp_port_list and self.open_com_port != None:
                        self.com_state = 2

            elif self.com_state == 2:
                set_try_num = 300
                try_num = 0
                while try_num < set_try_num:
                    try:
                        self.com_ser = serial.Serial(self.open_com_port, self.baud, timeout = 1)
                        self.com_state = 1
                        break

                    except Exception as e:
                        time.sleep(0.01)

                    try_num += 1
                if try_num == set_try_num:

                    self.com_state = 0
                    self.open_com_port = None
                    try:
                        if self.com_ser != None:
                            self.com_ser.close()

                    except Exception as e:
                        print('serial error ' + str(e))

                    self.com_ser = None

                    if isinstance(self.serial_close_callback, str):
                        exec(self.serial_close_callback)
                    elif callable(self.serial_close_callback):
                        self.serial_close_callback()

        return
