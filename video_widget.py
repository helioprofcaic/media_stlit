from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter

class VideoOutputWidget(QWidget):
    """Widget personalizado para renderizar vídeo e capturar mouse"""
    def __init__(self, double_click_callback, mouse_move_callback, single_click_callback):
        super().__init__()
        self.setStyleSheet("background-color: black;")
        self.setMouseTracking(True)
        self.double_click_callback = double_click_callback
        self.mouse_move_callback = mouse_move_callback
        self.single_click_callback = single_click_callback
        self._current_image = None

    def set_frame(self, image):
        self._current_image = image
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self._current_image and not self._current_image.isNull():
            # Escala a imagem mantendo proporção
            scaled = self._current_image.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            # Centraliza
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawImage(x, y, scaled)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.double_click_callback:
            self.double_click_callback()
        event.accept()

    def mouseMoveEvent(self, event):
        if self.mouse_move_callback:
            self.mouse_move_callback(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.single_click_callback:
                self.single_click_callback()
        event.accept()