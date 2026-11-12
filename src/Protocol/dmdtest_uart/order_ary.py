# coding: utf-8
"""
OrderAry 伪随机数据模型 (搬运自 mcu_ll_drivers_tester/ll_drivers_tester_host/python/order_ary.py)

两端独立生成 data[i] = from + (i % (to-from+1)) 后直接比对 —— 循环字符模式对
错位、丢字节、重复、乱序极其敏感, 任一字节偏移即比对失败, 无需协议帧即可验证数据完整性;
每用例换起始字符防上一用例残留数据"碰巧"通过。from == to 即全同字节。
"""


class OrderAry:
    def __init__(self, size: int, from_char: int = ord('A'), to_char: int = ord('Z')):
        """构造伪随机循环字符序列 data[i] = from + (i % (to-from+1)), 末尾补 '\0'

        Args:
            size: 数组大小(字节数), 0 表示空序列
            from_char: 起始字符码点(0~255), 默认 'A'; from == to 即全同字节
            to_char: 结束字符码点(0~255), 默认 'Z'; 区间无效时按单字符处理
        """
        if not isinstance(size, int) or size < 0:
            raise ValueError("size 必须是一个非负整数")

        self._size = size
        self._data = bytearray(size + 1)  # +1 用于存储 '\0'

        if size > 0:
            from_ord = from_char & 0xff
            to_ord = to_char & 0xff
            char_range = to_ord - from_ord + 1

            if char_range <= 0:
                char_range = 1  # 如果范围无效，则使用单个字符

            for i in range(size):
                char_code = from_ord + (i % char_range)
                self._data[i] = char_code
            self._data[size] = 0  # '\0'

    def size(self) -> int:
        """查询数组大小

        Returns:
            int: 构造时传入的字节数(不含末尾 '\0')
        """
        return self._size

    def __getitem__(self, index: int) -> str:
        """按索引取字符

        Args:
            index: 索引位置, 有效范围 [0, size-1]

        Returns:
            str: 该位置的单字符

        Raises:
            TypeError: index 非整数
            IndexError: index 超出范围
        """
        if not isinstance(index, int):
            raise TypeError("索引必须是整数")
        if index < 0 or index >= self._size:
            raise IndexError(f"索引 {index} 超出范围 [0, {self._size - 1}]")
        return chr(self._data[index])

    def __setitem__(self, index: int, value: str):
        """按索引设置字符

        Args:
            index: 索引位置, 有效范围 [0, size-1]
            value: 要设置的字符, 必须为单一字符, 按 ord 写入

        Raises:
            TypeError: index 非整数或 value 非 str
            IndexError: index 超出范围
            ValueError: value 不是单一字符
        """
        if not isinstance(index, int):
            raise TypeError("索引必须是整数")
        if index < 0 or index >= self._size:
            raise IndexError(f"索引 {index} 超出范围 [0, {self._size - 1}]")
        if not isinstance(value, str) or len(value) != 1:
            raise ValueError("value 必须是一个单一的字符")
        self._data[index] = ord(value)

    def __eq__(self, other) -> bool:
        """比较两个 OrderAry 实例是否相等

        Args:
            other: 另一个对象, 非 OrderAry 实例直接判不等

        Returns:
            bool: 大小与内容均相同返回 True, 否则 False
        """
        if not isinstance(other, OrderAry):
            return False
        if self._size != other._size:
            return False
        return self._data[:self._size] == other._data[:other._size]

    def __ne__(self, other) -> bool:
        """比较两个 OrderAry 实例是否不等

        Args:
            other: 另一个对象

        Returns:
            bool: 与 __eq__ 相反 —— 大小或内容不同返回 True
        """
        return not self.__eq__(other)

    def __repr__(self) -> str:
        """返回 OrderAry 的调试字符串表示

        Returns:
            str: 形如 "OrderAry(size=N, data='...')" 的可读文本
        """
        chars = ''.join(self[i] for i in range(self._size))
        return f"OrderAry(size={self._size}, data='{chars}')"

    def to_string(self) -> str:
        """返回数组内容的字符串表示

        Returns:
            str: 全部字节的字符拼接(不含末尾 '\0')
        """
        return ''.join(self[i] for i in range(self._size))

    def to_bytes(self) -> bytes:
        """返回数组内容的字节表示

        Returns:
            bytes: 与 MCU 侧 order_ary 逐字节一致的可直接比对数据(不含末尾 '\0')
        """
        return bytes(self._data[:self._size])
