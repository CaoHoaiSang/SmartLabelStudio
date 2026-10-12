import sys
import os
import math
import time
from PySide6.QtCore import QObject, Signal as pyqtSignal, QRect, QPoint, QMutex, QMutexLocker
from PySide6.QtGui import QTransform
import numpy as np
import cv2
from cv2 import ximgproc
from collections import deque
import traceback
import VariableManager
from MatrixTool import map_point_perspective, map_image_perspective
from PythonScriptExecutor import PythonScriptExecutor
import testrknn
from CameraCalibration import CameraCalibration

class VisionTool(QObject):
    detected = pyqtSignal(list)
    detect_image_ready = pyqtSignal(np.ndarray)
    display_image_ready = pyqtSignal(np.ndarray, list)
    origin_image_ready = pyqtSignal(np.ndarray)
    wrap_image_ready = pyqtSignal(np.ndarray)

    checking_area_ready = pyqtSignal()
    send_request_camera_image_signal = pyqtSignal(str, np.ndarray)

    # Tín hiệu cho Python script
    script_status = pyqtSignal(str, str, object)  # script_id, status_type, data

    trigger_capture_signal = pyqtSignal()
    detected_signal = pyqtSignal()
    clear_old_objects_signal = pyqtSignal()

    calib_status_signal = pyqtSignal(np.ndarray, int, str)

    crop_template_image_done = pyqtSignal(bool, str, str, str)  # success, image_name, project_name, message

    def __init__(self):
        super().__init__()

        self.mutex = QMutex()
        self.MappingMatrix = None
        self.perspective_matrix = None
        self.image_to_conveyor_matrix = None
        self.crop_img_rect = None

        self.is_wrap_crop_image = True

        self.origin_image = None
        self.detecting_image = None
        self.wrap_image = None
        self.preview_image = None

        self.color_type = [(0, 255, 0), (255, 0, 0), (0, 0, 255), (0, 255, 255), (255, 0, 255), (255, 255, 0), (200, 200, 200)]
        
        self.is_calibrate = 0

        # Khởi tạo PythonScriptExecutor
        self.script_executor = None
        
        # Lưu trữ ID của script đang chạy
        self.current_script_id = None

        self.is_density_scale = True

        self.vision_code = None
        self.vision_compiled_code = None
        self.is_running_vision_code = False

        self.is_aix_enabled = bool(int(VariableManager.instance.get("aix.enabled", "1")))
        self.custom_rknn = None

        self.is_request_camera_image = False
        self.request_camera_image_type = None

        self.is_request_capture_image = False

        self.is_calibrate_camera = False
        self.image_for_calibrate_count = 0
        self.this_frame_is_added = False

        self.tracking_objs = []

        # Camera calibration for lens distortion correction
        self.camera_calibration = CameraCalibration()
        self.enable_lens_distortion_correction = bool(int(VariableManager.instance.get("camera.main_camera.lens_distortion_correction", "0")))

        self.is_template_matching_enabled = False
        self.template_folder = None
        self.templates_list = []

        self.block_template_folder = None
        self.block_templates_list = []

        self.find_type_cfg = False
        self.find_center_cfg = False
        self.find_size_cfg = False
        self.find_angle_cfg = False
        self.roi_scale = 1.0
        self.template_threshold = 0.8
        self.template_match_scale = 0.25
        self.template_match_method = cv2.TM_CCOEFF_NORMED

        self.load_system_settings()
        self.load_settings()

    def set_calibrate_state(self, is_calibrate):
        with QMutexLocker(self.mutex):
            self.is_calibrate = is_calibrate

    
    def crop_obj_position(self, obj_x, obj_y):
        x1 = self.crop_img_rect.topLeft().x()
        y1 = self.crop_img_rect.topLeft().y()

        x1 = max(0, x1)
        y1 = max(0, y1)

        new_x = obj_x - x1
        new_y = obj_y - y1

        return new_x, new_y
    
    def crop_image(self, img):
        start_row = self.crop_img_rect.topLeft().y()
        end_row = self.crop_img_rect.bottomRight().y()
        start_col = self.crop_img_rect.topLeft().x()
        end_col = self.crop_img_rect.bottomRight().x()

        cropped = img[start_row:end_row, start_col:end_col]

        return cropped
    
    def run(self):
        self.script_executor = PythonScriptExecutor(vision_instance=self)

        # self.custom_rknn = testrknn.init_rknn_model("models/aligner.rknn")

    def _load_template_images_from_disk(self, folder_name):
        """Đọc mọi ảnh template (grayscale) trong thư mục templates/<folder_name>."""
        templates = []
        if folder_name is None:
            return templates
        folder_path = os.path.join("templates", str(folder_name))
        if not os.path.isdir(folder_path):
            return templates
        for fname in sorted(os.listdir(folder_path)):
            if not fname.lower().endswith(('.jpg', 'jpeg', 'png', 'bmp')):
                continue
            path = os.path.join(folder_path, fname)
            tpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if tpl is not None:
                templates.append(tpl)
        return templates

    def load_system_settings(self):
        self.is_template_matching_enabled = bool(int(VariableManager.instance.get("template_matching.enabled", "0")))
        template_folder_value = VariableManager.instance.get("template_matching.template_folder", "default")
        if isinstance(template_folder_value, list):
            self.template_folder = template_folder_value[0] if len(template_folder_value) > 0 else "default"
        else:
            self.template_folder = str(template_folder_value) if template_folder_value is not None else "default"

        self.templates_list = self._load_template_images_from_disk(self.template_folder)

        self.is_density_scale = VariableManager.instance.get("object_tracking.mode", "classify") == "density_scale"

        # Config các trường output của refine
        self.find_type_cfg   = bool(int(VariableManager.instance.get("template_matching.find_type",   "0")))
        self.find_center_cfg = bool(int(VariableManager.instance.get("template_matching.find_center", "1")))
        self.find_size_cfg   = bool(int(VariableManager.instance.get("template_matching.find_size",   "0")))
        self.find_angle_cfg  = bool(int(VariableManager.instance.get("template_matching.find_angle",  "1")))

        # ROI scale: vùng crop quanh mỗi object AI để chạy template match (1.0 = đúng bằng bbox AI)
        self.roi_scale = float(VariableManager.instance.get("template_matching.roi_scale", "1.0"))

        self.template_threshold = float(VariableManager.instance.get("template_matching.threshold", "0.8"))
        self.template_match_scale = float(VariableManager.instance.get("template_matching.match_scale", "0.25"))
        self.template_match_method = cv2.TM_CCOEFF_NORMED
        
        # Load lens distortion correction setting
        self.enable_lens_distortion_correction = bool(int(VariableManager.instance.get("camera.main_camera.lens_distortion_correction", "0")))
        
        # Load filter settings
        self.filter_enabled = bool(int(VariableManager.instance.get("aix.filter_enabled", "0")))
        self.filter_min = float(VariableManager.instance.get("aix.filter_min", 0))
        self.filter_max = float(VariableManager.instance.get("aix.filter_max", 100))

    def load_settings(self):
        with QMutexLocker(self.mutex):
            default_perspective_transform = [
                [0.919916718, -0.198982145, 79.4047972],
                [0.00645335591, 0.849063021, 9.98924454],
                [-0.00000347494551, -0.000200068309, 1.0]
            ]

            default_perspective_transform = np.array(default_perspective_transform, dtype=np.float32)

            default_image_to_real_world = QTransform(
                -0.372541, -0.001901, 0.0,
                0.001901, -0.372541, 0.0,
                120.089456, -98.113319, 1.0
            )

            default_crop_rect = (544, 237, 877, 735)

            # perspective matrix
            self.perspective_matrix = VariableManager.instance.get("perspective_matrix", default_perspective_transform)
            # print("perspective_matrix:", self.perspective_matrix)

            # image to real world matrix
            self.image_to_conveyor_matrix = VariableManager.instance.get("image_to_real_world_matrix", default_image_to_real_world)
            # print("image_to_conveyor_matrix:", self.image_to_conveyor_matrix)

            # crop image
            crop_rect = VariableManager.instance.get("crop_rect", default_crop_rect)
            # print("crop_rect:", crop_rect)

            if crop_rect is not None:
                (x1, y1, w, h) = crop_rect
                self.crop_img_rect = QRect(int(x1), int(y1), int(w), int(h))
            else:
                print("Warning: crop_rect not found in settings, using default values")
                self.crop_img_rect = QRect(100, 100, 640, 480)  # Default values

            self.image_to_real_scale = self.find_scale_value()
            self.find_checking_area()

    # find scale value for convert from image to real
    def find_scale_value(self):
        _image_point_1= QPoint(100, -150)
        _image_point_2= QPoint(300, -500)

        _real_point_1 = self.image_to_conveyor_matrix.map(_image_point_1)
        _real_point_2 = self.image_to_conveyor_matrix.map(_image_point_2)

        _image_distance = math.sqrt((_image_point_2.x() - _image_point_1.x())**2 + (_image_point_2.y() - _image_point_1.y())**2)
        _real_distance = math.sqrt((_real_point_2.x() - _real_point_1.x())**2 + (_real_point_2.y() - _real_point_1.y())**2)

        return _real_distance / _image_distance

    def find_checking_area(self):
        _image_point_1= QPoint(0, 0)
        _image_point_2= QPoint(self.crop_img_rect.width(), -self.crop_img_rect.height())

        _real_point_1 = self.image_to_conveyor_matrix.map(_image_point_1)
        _real_point_2 = self.image_to_conveyor_matrix.map(_image_point_2)

        _min_gx = min(_real_point_1.x(), _real_point_2.x())
        _max_gx = max(_real_point_1.x(), _real_point_2.x())
        _min_gy = min(_real_point_1.y(), _real_point_2.y())
        _max_gy = max(_real_point_1.y(), _real_point_2.y())
        
        VariableManager.instance.set("checking_area", (_min_gx, _min_gy, _max_gx, _max_gy))
        VariableManager.instance.save()
        self.checking_area_ready.emit()

    def capture_and_process(self, robot_index):
        self.trigger_capture_signal.emit()
        self.is_request_capture_image = True 

    def set_calibrate_camera(self, state):
        if state == 0:
            self.is_calibrate_camera = True
        elif state == 1:
            self.is_calibrate_camera = False
        elif state == 2:
            self.get_image_for_calibrate()
        elif state == 3:
            self.calibrate_camera()

    def send_calibrate_status(self, image, state, info=None):
        # nếu self.preview_image kích thước quá lớn thì giảm kích thước xuống w khoản 800
        if image.shape[1] > 700:
            __image = cv2.resize(image, (700, int(image.shape[0] * 700 / image.shape[1])))
        else:
            __image = image
        
        if info is not None:
            self.calib_status_signal.emit(__image, state, info)
        else:
            self.calib_status_signal.emit(__image, state)

    def get_image_for_calibrate(self):
        if self.is_calibrate_camera == True and self.this_frame_is_added == False:
            _is_ok, _n_markers, _n_charuco_corners = self.camera_calibration.add_frame(self.origin_image)
            if _is_ok == True:
                self.image_for_calibrate_count += 1
                self.this_frame_is_added = True

    def calibrate_camera(self):
        if self.is_calibrate_camera == True:
            _is_ok = self.camera_calibration.calibrate_from_accumulated()
            if _is_ok == True:
                self.is_calibrate_camera = False
                self.send_calibrate_status(self.origin_image, 33, "Calibrate success")
            else:
                self.send_calibrate_status(self.origin_image, 34, "Calibrate failed")

    def detect(self, image):
        try:
            self.detecting_image = image.copy()
            self.origin_image = image.copy()

            if self.is_calibrate_camera == True:
                self.this_frame_is_added = False
                _calib_image = self.camera_calibration.visualize_charuco_detection(self.origin_image)
                self.send_calibrate_status(_calib_image, 32, "Image: " + str(self.image_for_calibrate_count) + " / Suggestion: 12")
                return

            # 🔧 LENS DISTORTION CORRECTION - Khử cong ống kính TRƯỚC perspective transform
            if self.enable_lens_distortion_correction and self.camera_calibration.is_calibrated():
                self.detecting_image = self.camera_calibration.undistort_image(self.detecting_image)
                # print("✅ Applied lens distortion correction")

            if self.is_wrap_crop_image == True:
                self.detecting_image = map_image_perspective(self.detecting_image, self.perspective_matrix)
                # cv2.imwrite("wrap_image.jpg", self.detecting_image) 
                self.wrap_image = self.detecting_image.copy()

                self.detecting_image = self.crop_image(self.detecting_image)

            if self.is_request_camera_image == True:
                self.send_request_camera_image()

            self.preview_image = self.detecting_image.copy()
            self.detect_image_ready.emit(self.detecting_image)
            
            
            if self.is_aix_enabled == False:
                self._execute_script(self.vision_compiled_code)
                if self.is_request_capture_image == True:
                    self.is_request_capture_image = False
                    self.detected_signal.emit()
                self.send_preview_image()
            
        except Exception as e:
            # In ra lỗi
            print(e)
            traceback.print_exc()

    def get_objs_from_external(self, objs):
        self.tracking_objs = []
        self.filter_objs = []

        if self.is_aix_enabled and self.detecting_image is not None:
            if self.is_template_matching_enabled == True:
                # AI + template: refine/classify bằng detect_templates với danh sách template đã preload
                objs = self.refine_objects_with_templates(
                    objs,
                    templates=self.templates_list
                )

        for obj in objs:
            if self.is_wrap_crop_image == False:
                obj[1] = map_point_perspective(obj[1], self.perspective_matrix)
                obj[1] = self.crop_obj_position(obj[1][0], obj[1][1])
                obj[2] = map_point_perspective(obj[2], self.perspective_matrix)

            realPos = self.image_to_conveyor_matrix.map(QPoint(obj[1][0], -obj[1][1]))
            realWH = self.image_to_real_scale * QPoint(obj[2][0], obj[2][1])

            center_x = realPos.x()
            center_y = realPos.y()
            width = round(abs(realWH.x()))
            length = round(abs(realWH.y()))

            if self.filter_enabled == True:
                if width < self.filter_min or length < self.filter_min:
                    continue
                if width > self.filter_max or length > self.filter_max:
                    continue

            if width < 3 or length < 3:
                continue

            self.filter_objs.append(obj)

            angle = obj[3]

            _tracking_obj = [center_x, center_y, width, length, angle,  obj[0]]
            self.tracking_objs.append(_tracking_obj)

        if len(self.tracking_objs) > 0 or self.is_density_scale:
            self.detected.emit(self.tracking_objs)

        if self.is_request_capture_image == True:
            self.is_request_capture_image = False
            self.detected_signal.emit()
            
        self.preview_image = self.draw_rotated_objs(
            self.preview_image, self.filter_objs,
            ori_image_heading=self.is_aix_enabled and str(VariableManager.instance.get("aix.model_type", "DET")).upper() == "ORI",
        )
        
        if self.is_density_scale == False:
            self.send_preview_image()

    def find_display_angle(self, x):
        if x > 180:
            x = x - 360
        if x >= 0 and x <= 90:
            y = 90 - x
        elif x > 90 and x <= 180:
            y = 90 - x 
        elif x < 0 and x >= -90:
            y = 90 - x
        elif x < -90 and x >= -180:
            y = -270 - x
        else:
            y = None
            print("xxxx:", x)
        return y

    def draw_rotated_objs(self, image, objs, ori_image_heading=False):
        # print("objs_draw:", objs)
        draw = image.copy()
     
        for obj in objs:
            box = obj[1:4]
          
            angle = math.radians(box[2] if ori_image_heading else box[2] + 90)
            box[2] = self.find_display_angle(box[2] + 90)
            length = box[1][0] * (0.45 if ori_image_heading else 0.6)            

            end_x = int(length * math.cos(angle)) + box[0][0]
            end_y = - int(length * math.sin(angle)) + box[0][1]
            
            end = (int(end_x), int(end_y))
            start = (int(box[0][0]), int(box[0][1]))

            try:
                cv2.arrowedLine(draw, start, end, self.color_type[obj[0]], 2, tipLength=0.2)

                box = np.intp(cv2.boxPoints(box))
                draw = cv2.drawContours(draw, [box], 0, self.color_type[obj[0]], 2)
                
                # Hiển thị object type tại vị trí tâm của box
                center_x = int(start[0])  # Convert to int
                center_y = int(start[1])  # Convert to int
                obj_type = obj[0]
                cv2.putText(draw, str(obj_type), (center_x, center_y), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, self.color_type[obj_type], 2, cv2.LINE_AA)
                
                # hiển thị conf nếu có
                if len(obj) >= 5:
                    conf = obj[4]
                    cv2.putText(draw, f"{conf:.2f}", (center_x, center_y + 20), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.6, self.color_type[obj_type], 1, cv2.LINE_AA)
                    
                
            except Exception as e:
                print(f"Error in draw_rotated_objs: {e}")

        return draw

        # cv2.imwrite("detect_image.jpg", draw)

    def draw_rebalance_tasks(self, rebalance_tasks):
        # chuyển toạ độ từ real world sang image
        _image_to_real_matrix = self.image_to_conveyor_matrix.inverted()[0]

        for obj_x, obj_y, obj_width in rebalance_tasks:
            _obj = _image_to_real_matrix.map(QPoint(obj_x, obj_y))

            cv2.circle(self.preview_image, (int(_obj.x()), int(-_obj.y())), int(obj_width), (200, 200, 200), 2)
        
        self.send_preview_image()

    def send_preview_image(self):
        if self.is_calibrate == 0:
            # nếu self.preview_image kích thước quá lớn thì giảm kích thước xuống w khoản 800
            if self.preview_image.shape[1] > 800:
                __preview_image = cv2.resize(self.preview_image, (800, int(self.preview_image.shape[0] * 800 / self.preview_image.shape[1])))
            else:
                __preview_image = self.preview_image

            self.display_image_ready.emit(__preview_image, self.tracking_objs)
            self.tracking_objs = []
        elif self.is_calibrate == 1:
            self.display_image_ready.emit(self.origin_image, [])
        elif self.is_calibrate == 2:
            self.display_image_ready.emit(self.wrap_image, [])
        elif self.is_calibrate == 3:
            self.display_image_ready.emit(self.detecting_image, [])
    def get_origin_image(self):
        self.origin_image_ready.emit(self.origin_image)

    def _execute_script(self, code):
        if self.is_running_vision_code == False or code == None:
            return

        success, error = self.script_executor.execute_script(code)
        if success:
            pass
        else:
            self.script_status.emit(self.current_script_id, "run_error", error)
            print("error----", error)

    def execute_vision_code(self, script_id, code):
        self.vision_code = code
        self.vision_compiled_code = compile(code, '<string>', 'exec')
        self.is_running_vision_code = True
        self.current_script_id = script_id

        self.clear_old_objects_signal.emit()

        self.is_aix_enabled = bool(int(VariableManager.instance.get("aix.enabled", "1")))

    def stop_vision_code(self, script_id):
        # Best-effort stop:
        # - UI có thể gửi script_id sai (khi có nhiều program chạy song song).
        # - Nếu đang chạy, dừng theo script đang chạy thật.
        if not self.is_running_vision_code:
            return

        effective_script_id = script_id
        if self.current_script_id is not None and script_id != self.current_script_id:
            effective_script_id = self.current_script_id
            
        self.is_running_vision_code = False
        self.current_script_id = None

        self.script_status.emit(effective_script_id, 'stop_stopped', "Script execution stopped by user")
        self._clear_block_template_cache()

    def python_script_has_error(self, script_id, index = None):
        # Chỉ dừng vision nếu lỗi thuộc về chương trình đang chạy vision này
        if self.current_script_id is not None and script_id != self.current_script_id:
            return
        self.is_running_vision_code = False
        self.current_script_id = None
        self._clear_block_template_cache()

    def crop_image_with_rect(self, image, rect):
        start_row = max(0, rect.topLeft().y())
        end_row = min(image.shape[0], rect.bottomRight().y())
        start_col = max(0, rect.topLeft().x())
        end_col = min(image.shape[1], rect.bottomRight().x())
        
        return image[start_row:end_row, start_col:end_col]
    
    def filter_hsv(self, image, lower_hsv, upper_hsv):
        # Convert to HSV color space
        hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        
        # Create mask using HSV range
        lower_bound = np.array(lower_hsv, dtype=np.uint8)
        upper_bound = np.array(upper_hsv, dtype=np.uint8)
        mask = cv2.inRange(hsv_image, lower_bound, upper_bound)
        
        return mask

    def filter_threshold(self, image, threshold_value, max_value=255, threshold_type=cv2.THRESH_BINARY):
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray_image = image
        
        _, thresholded = cv2.threshold(gray_image, threshold_value, max_value, threshold_type)
        return thresholded

    # -------------------------------------------------------------------------
    # Template Matching
    # -------------------------------------------------------------------------

    def _template_match_config_dict(self, threshold=None, match_scale=None, method=None):
        return {
            "threshold": self.template_threshold if threshold is None else float(threshold),
            "match_scale": self.template_match_scale if match_scale is None else float(match_scale),
            "method": self.template_match_method if method is None else method,
        }

    def detect_templates(self, image, templates=None,
                        find_type=True, find_angle=False, find_size=False, angles=None,
                        match_config=None):
        if image is None or image.size == 0 or not templates:
            return []

        if match_config is None:
            match_config = self._template_match_config_dict()

        results = []
        for idx, tpl_img in enumerate(templates):
            obj_type = idx if find_type else 0
            results.extend(self._detect_one_template(
                image, tpl_img, obj_type,
                find_angle=find_angle, find_size=find_size,
                config=match_config, angles_override=angles
            ))
        return results

    def _detect_one_template(self, image, template, object_type, find_angle=False, find_size=False, config=None, angles_override=None):
        if config is None:
            config = self._template_match_config_dict()
        thresh = config["threshold"]
        method = config["method"]
        scale = config.get("match_scale", 1.0)

        img = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        tpl = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) if len(template.shape) == 3 else template

        img = cv2.GaussianBlur(img, (3, 3), 0)
        tpl = cv2.GaussianBlur(tpl, (3, 3), 0)

        img = cv2.Canny(img, 50, 150)
        tpl = cv2.Canny(tpl, 50, 150)

        h_tpl, w_tpl = tpl.shape[:2]

        if scale < 1.0:
            img_w = cv2.resize(img, (max(1, int(img.shape[1] * scale)), max(1, int(img.shape[0] * scale))))
            tpl_w = cv2.resize(tpl, (max(1, int(w_tpl * scale)), max(1, int(h_tpl * scale))))
        else:
            img_w, tpl_w = img, tpl

        h_w, w_w = tpl_w.shape[:2]
        if img_w.shape[0] < h_w or img_w.shape[1] < w_w:
            return []

        is_sqdiff = method in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED)

        def _run_match(tpl_rot):
            if img_w.shape[0] < tpl_rot.shape[0] or img_w.shape[1] < tpl_rot.shape[1]:
                return None, None
            res = cv2.matchTemplate(img_w, tpl_rot, method)
            mn, mx, ml, xl = cv2.minMaxLoc(res)
            if is_sqdiff:
                return (-mn, ml) if mn <= (1.0 - thresh) else (None, None)
            return (mx, xl) if mx >= thresh else (None, None)

        def _to_orig(loc, tpl_shape):
            return (loc[0] + tpl_shape[1] / 2.0) / scale, (loc[1] + tpl_shape[0] / 2.0) / scale

        def _rotate_tpl(src, angle_deg):
            if abs(angle_deg % 360) < 1e-3:
                return src
            h, w = src.shape[:2]
            M = cv2.getRotationMatrix2D((w / 2, h / 2), float(angle_deg), 1.0)
            cos, sin = np.abs(M[0, 0]), np.abs(M[0, 1])
            nW = int((h * sin) + (w * cos))
            nH = int((h * cos) + (w * sin))
            M[0, 2] += (nW / 2) - w / 2
            M[1, 2] += (nH / 2) - h / 2
            return cv2.warpAffine(src, M, (nW, nH), flags=cv2.INTER_LINEAR, borderValue=0)

        if find_angle:
            angles = angles_override if (angles_override is not None and len(angles_override) > 0) else tuple(range(0, 360, 10))
            best_score, best_cx, best_cy, best_angle = None, None, None, None

            for angle_deg in angles:
                tpl_rot = _rotate_tpl(tpl_w, angle_deg)
                score, loc = _run_match(tpl_rot)
                if score is None:
                    continue
                if best_score is None or score > best_score:
                    best_score = score
                    best_cx, best_cy = _to_orig(loc, tpl_rot.shape)
                    best_angle = angle_deg

            if best_cx is None:
                return []
            angle_norm = ((float(best_angle) + 180.0) % 360.0) - 180.0
            # return [[object_type, (float(best_cx), float(best_cy)), (float(w_tpl), float(h_tpl)), int(angle_norm)]]
            return [[object_type, (float(best_cx), float(best_cy)), (float(w_tpl), float(h_tpl)), int(angle_norm), float(best_score)]]

        score, loc = _run_match(tpl_w)
        if score is None:
            return []
        cx, cy = _to_orig(loc, tpl_w.shape)
        # return [[object_type, (float(cx), float(cy)), (float(w_tpl), float(h_tpl)), 0]]
        return [[object_type, (float(cx), float(cy)), (float(w_tpl), float(h_tpl)), 0, float(score)]]

    def refine_objects_with_templates(
        self,
        objs,
        templates=None,
        *,
        threshold=None,
        match_scale=None,
        roi_scale=None,
        find_type=None,
        find_center=None,
        find_size=None,
        find_angle=None,
        method=None,
    ):
        if self.detecting_image is None or objs is None or len(objs) == 0:
            return objs
        if not templates:
            return objs

        rs = self.roi_scale if roi_scale is None else float(roi_scale)
        ft = self.find_type_cfg if find_type is None else bool(find_type)
        fc = self.find_center_cfg if find_center is None else bool(find_center)
        fsz = self.find_size_cfg if find_size is None else bool(find_size)
        fa = self.find_angle_cfg if find_angle is None else bool(find_angle)
        match_config = self._template_match_config_dict(
            threshold=threshold, match_scale=match_scale, method=method
        )

        h_img, w_img = self.detecting_image.shape[:2]
        result_list = []

        for obj in objs:
            if len(obj) < 4:
                continue

            # obj_type, (cx, cy), (w, h), angle = obj
            obj_type, (cx, cy), (w, h), angle = obj[:4]

            # half_w = (w * rs) / 2.0
            # half_h = (h * rs) / 2.0
            roi_side = max(float(w), float(h)) * rs
            half_w = roi_side / 2.0
            half_h = roi_side / 2.0

            x1 = int(cx - half_w)
            y1 = int(cy - half_h)
            x2 = int(cx + half_w)
            y2 = int(cy + half_h)

            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(w_img, x2)
            y2 = min(h_img, y2)

            if x2 <= x1 or y2 <= y1:
                continue

            roi_bgr = self.detecting_image[y1:y2, x1:x2]
            # Pre-convert sang grayscale một lần, tránh convert lặp lại trong mỗi lần match template
            roi = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY) if len(roi_bgr.shape) == 3 else roi_bgr

            # ai_angle = int(angle) % 360
            # angles_tuple = tuple(sorted(set([ai_angle, (ai_angle + 180) % 360])))

            # matches = self.detect_templates(
            #     roi,
            #     templates=templates,
            #     find_type=True,
            #     find_angle=True,
            #     find_size=fsz,
            #     angles=angles_tuple,
            #     match_config=match_config,
            # )

            # if len(matches) == 0:
            #     continue
            # Use Template Matching settings from UI/config.
            # SEG angle can be wrong, so do not force matching only at AI angle.
            angles_tuple = tuple(range(0, 360, 15)) if fa else None

            print(
                "[TM DEBUG]",
                "templates=", len(templates),
                "roi=", roi.shape,
                "tpl0=", templates[0].shape if len(templates) > 0 else None,
                "threshold=", match_config["threshold"],
                "scale=", match_config["match_scale"],
                "roi_scale=", rs,
                "ft=", ft,
                "fc=", fc,
                "fsz=", fsz,
                "fa=", fa,
                "obj=", obj
            )
            matches = self.detect_templates(
                roi,
                templates=templates,
                find_type=ft,
                find_angle=fa,
                find_size=fsz,
                angles=angles_tuple,
                match_config=match_config,
            )
            if len(matches) > 0:
                print("[TM] best match =", matches[0])
            else:
                print("[TM] no match, keep AI object")

            if len(matches) == 0:
                # Keep original AI object when template matching fails.
                # This prevents preview from becoming empty.
                result_list.append([int(obj_type), (float(cx), float(cy)), (float(w), float(h)), int(angle)])
                continue

            roi_cx = (x2 - x1) / 2.0
            roi_cy = (y2 - y1) / 2.0

            # Chọn match tốt nhưng không cho nhảy quá xa tâm object AI.
            # Vì template có nền, nếu chỉ chọn score cao nhất có thể match nhầm vùng nền.
            best_match = None
            best_value = None

            for m in matches:
                score = float(m[4]) if len(m) >= 5 else 0.0
                m_type_tmp, (m_cx_tmp, m_cy_tmp), (m_w_tmp, m_h_tmp), m_angle_tmp = m[:4]

                dx = m_cx_tmp - roi_cx
                dy = m_cy_tmp - roi_cy
                dist = math.sqrt(dx * dx + dy * dy)

                # Giới hạn match không được lệch quá xa object AI
                max_dist = max(float(w), float(h)) * 0.35

                if dist > max_dist:
                    print("[TM FILTER] reject far match:", m, "dist=", dist, "max_dist=", max_dist)
                    continue

                # Ưu tiên score cao, nhưng phạt nếu lệch xa tâm AI
                value = score - 0.001 * dist

                if best_value is None or value > best_value:
                    best_value = value
                    best_match = m

            if best_match is None:
                print("[TM SELECT] no valid match after filter, keep AI object")
                result_list.append([
                    int(obj_type),
                    (float(cx), float(cy)),
                    (float(w), float(h)),
                    int(round(angle))
                ])
                continue

            print("[TM SELECT]", best_match, "value=", best_value)

            m_type, (m_cx, m_cy), (m_w, m_h), m_angle = best_match[:4]
            global_cx_tpl = x1 + m_cx
            global_cy_tpl = y1 + m_cy

            def _norm180(a):
                return ((float(a) + 180.0) % 360.0) - 180.0

            def _angle_diff(a, b):
                return abs(((float(a) - float(b) + 180.0) % 360.0) - 180.0)

            def _unwrap_ai_raw_angle_by_template(ai_raw_angle, template_angle):
                """
                Giữ góc/raw angle của AI để box vẫn khít.
                Template chỉ quyết định có cộng thêm 180° hay không.

                Lưu ý:
                draw_rotated_objs đang vẽ bằng angle + 90,
                nên khi so với template_angle phải so sánh ai_raw_angle + 90.
                """
                candidates = [
                    _norm180(ai_raw_angle),
                    _norm180(ai_raw_angle + 180.0)
                ]

                target = _norm180(template_angle)

                def display_angle_from_raw(raw_angle):
                    return _norm180(raw_angle + 90.0)

                best = min(
                    candidates,
                    key=lambda c: _angle_diff(display_angle_from_raw(c), target)
                )

                return best

            # Type: bật Type thì lấy type từ template, tắt thì giữ type AI
            out_type = int(m_type) if ft else int(obj_type)

            # Center: bật Center thì lấy tâm template, tắt thì giữ tâm AI
            out_cx = float(global_cx_tpl) if fc else float(cx)
            out_cy = float(global_cy_tpl) if fc else float(cy)

            # Size: bật Size thì lấy size template, tắt thì giữ size AI
            out_w = float(m_w) if fsz else float(w)
            out_h = float(m_h) if fsz else float(h)

            # Angle:
            # - Angle OFF: giữ góc AI
            # - Angle ON: dùng template để sửa nhánh 180° cho góc AI
            if fa:
                out_angle = _unwrap_ai_raw_angle_by_template(float(angle), float(m_angle))
            else:
                out_angle = float(angle)

            print(
                "[TM OUT]",
                "ft=", ft,
                "fc=", fc,
                "fsz=", fsz,
                "fa=", fa,
                "ai=", [obj_type, (cx, cy), (w, h), angle],
                "template=", [m_type, (global_cx_tpl, global_cy_tpl), (m_w, m_h), m_angle],
                "out=", [out_type, (out_cx, out_cy), (out_w, out_h), out_angle]
            )

            result_list.append([
                out_type,
                (out_cx, out_cy),
                (out_w, out_h),
                int(round(out_angle))
            ])

        return result_list

    def _ensure_block_templates_cached(self, folder_name):
        name = str(folder_name) if folder_name is not None else "default"
        if self.block_template_folder == name:
            return
        self.block_template_folder = name
        self.block_templates_list = self._load_template_images_from_disk(name)

    def _clear_block_template_cache(self):
        self.block_template_folder = None
        self.block_templates_list = []

    def refine_objects_with_block_templates(
        self,
        objs,
        template_folder,
        *,
        threshold=None,
        match_scale=None,
        roi_scale=None,
        find_type=None,
        find_center=None,
        find_size=None,
        find_angle=None,
        method=None,
    ):
        if template_folder is None:
            return objs
        folder = str(template_folder).strip()
        if not folder:
            return objs
        self._ensure_block_templates_cached(folder)
        if not self.block_templates_list:
            return objs
        return self.refine_objects_with_templates(
            objs,
            templates=self.block_templates_list,
            threshold=threshold,
            match_scale=match_scale,
            roi_scale=roi_scale,
            find_type=find_type,
            find_center=find_center,
            find_size=find_size,
            find_angle=find_angle,
            method=method,
        )

    def denoise_image(self, image, method='gaussian', kernel_size=5):
        if method == 'gaussian':
            return cv2.GaussianBlur(image, (kernel_size, kernel_size), 0)
        elif method == 'median':
            return cv2.medianBlur(image, kernel_size)
        elif method == 'bilateral':
            return cv2.bilateralFilter(image, kernel_size, 75, 75)
        elif method == 'morphology_open':
            kernel = np.ones((kernel_size, kernel_size), np.uint8)
            # Apply morphological operations (opening: erosion followed by dilation)
            return cv2.morphologyEx(image, cv2.MORPH_OPEN, kernel)
        elif method == 'morphology_close':
            kernel = np.ones((kernel_size, kernel_size), np.uint8)
            # Apply morphological operations (closing: dilation followed by erosion)
            return cv2.morphologyEx(image, cv2.MORPH_CLOSE, kernel)
        else:
            return image

    def find_contours(self, image, min_area=100, max_area=100000):
        contours, _ = cv2.findContours(image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        results = []
        for contour in contours:
            area = cv2.minAreaRect(contour)
            area_width = area[1][0]
            area_length = area[1][1]
            if area_width < area_length:
                area_width, area_length = area_length, area_width

            if area_width < min_area or area_length < min_area or area_width > max_area or area_length > max_area:
                continue

            results.append(contour)
            
        return results
    
    def get_skeletons_from_contours(self, image, contours):
        skeletons = []
        for contour in contours:
            filled_mask = np.zeros_like(image)
            cv2.drawContours(filled_mask, [contour], -1, 255, cv2.FILLED)

            skeleton = ximgproc.thinning(filled_mask, None, ximgproc.THINNING_ZHANGSUEN)
            skeletons.append(skeleton)

        return skeletons
    
    def is_rotated_box_touching_edge(self, cx, cy, w, h, angle_deg, img_width, img_height, margin=5):
        rect = ((cx, cy), (w, h), angle_deg)
        box_points = cv2.boxPoints(rect)  # Lấy 4 góc
        
        for point in box_points:
            px, py = point
            if px < margin or px > (img_width - margin):
                return True
            if py < margin or py > (img_height - margin):
                return True
        
        return False
    
    # tạo hàm tìm góc, tâm, kích thước của object với minAreaRect
    def find_rotation_objects_from_contours(self, contours, image=None):
        results = []
        # Dùng image truyền vào, hoặc detecting_image (cùng frame với contours) để kiểm tra chạm viền
        img_for_edge = image if image is not None else getattr(self, 'detecting_image', None)
        for contour in contours:
            (cx, cy), (w, h), ang = cv2.minAreaRect(contour)  # ang in (-90, 0]

            if w < h:
                corrected_angle = -ang  # chuyển về dương
            else:
                corrected_angle = -ang + 90  # thêm 90 độ để điều chỉnh
                w, h = h, w

            # Đảm bảo kết quả nằm trong [0, 180)
            ang = int(corrected_angle % 180)

            if img_for_edge is not None:
                img_height, img_width = img_for_edge.shape[:2]
                if self.is_rotated_box_touching_edge(cx, cy, w, h, ang, img_width, img_height, margin=10):
                    continue

            info = [
                0,                          # id
                (float(cx), float(cy)),     # (x, y)
                (float(w), float(h)),       # (w, h) (w >= h)
                int(ang)                  
            ]

            results.append(info)
        return results
    
    def get_neighbors_8(self, r, c, W, H):
        neighbors = []
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if 0 <= nr < H and 0 <= nc < W:
                    neighbors.append((nr, nc))
        return neighbors
    
    def find_endpoints(self, skel):
        # Sử dụng numpy vectorization thay vì vòng lặp
        kernel = np.array([[1,1,1],[1,0,1],[1,1,1]], dtype=np.uint8)
        neighbors = cv2.filter2D((skel==255).astype(np.uint8), -1, kernel)
        return list(zip(*np.where((skel==255) & (neighbors==1))))
    
    def bfs_longest_path(self, skel, start):
        H, W = skel.shape
        visited = np.zeros((H, W), dtype=bool)
        parent = dict()

        queue = deque([start])
        visited[start[0], start[1]] = True
        farthest = start

        while queue:
            r, c = queue.popleft()
            farthest = (r, c)
            for (nr, nc) in self.get_neighbors_8(r, c, W, H):
                if (not visited[nr, nc]) and skel[nr, nc] == 255:
                    visited[nr, nc] = True
                    parent[(nr, nc)] = (r, c)
                    queue.append((nr, nc))
        return farthest, parent
    
    def reconstruct_path(self, parent, start, end):
        path = []
        cur = end
        while cur != start:
            path.append(cur)
            cur = parent[cur]
        path.append(start)
        path.reverse()
        return path
    
    def calculate_perpendicular_angle(self, point1, point2, mid_point):
        (r1, c1) = point1
        (r2, c2) = point2
        (mr, mc) = mid_point

        # Calculate the direction vector of the line segment
        direction_vector = (c2 - c1, r2 - r1)

        # Calculate the intersection point
        if direction_vector[0] == 0:  # Vertical line
            intersection_point = (mr, c1)
        elif direction_vector[1] == 0:  # Horizontal line
            intersection_point = (r1, mc)
        else:
            slope = direction_vector[1] / direction_vector[0]
            intercept = r1 - slope * c1
            perpendicular_slope = -1 / slope
            perpendicular_intercept = mr - perpendicular_slope * mc
            intersection_c = (perpendicular_intercept - intercept) / (slope - perpendicular_slope)
            intersection_r = slope * intersection_c + intercept
            intersection_point = (int(intersection_r), int(intersection_c))

        # Calculate the angle of the vector from mid_point to the intersection point
        vector = (intersection_point[1] - mc, intersection_point[0] - mr)
        angle_rad = math.atan2(vector[1], vector[0])
        angle_deg = angle_rad * 180.0 / math.pi

        return angle_deg

    def get_midpoint_and_perp_angle(self, skel):
        # 1) Tìm endpoints
        endpoints = self.find_endpoints(skel)
        if len(endpoints) < 1:
            return None, None

        # 2) BFS lần 1: endpoint đầu => far1
        far1, par1 = self.bfs_longest_path(skel, endpoints[0])
        # 3) BFS lần 2: far1 => far2
        far2, par2 = self.bfs_longest_path(skel, far1)
        # 4) Dựng path đường kính
        path_diameter = self.reconstruct_path(par2, far1, far2)
        if len(path_diameter) < 2:
            return None, None

        # 5) Lấy midpoint (phần tử giữa)
        mid_idx = len(path_diameter)//2
        midpoint = path_diameter[mid_idx]

        # 6) Dùng 2 điểm đầu/cuối
        (r1, c1) = path_diameter[0]
        (r2, c2) = path_diameter[-1]

        # 7) Tính góc vuông góc
        angle_deg = self.calculate_perpendicular_angle((r1, c1), (r2, c2), midpoint)

        return midpoint, angle_deg
    
    def get_midpoints_and_perp_angles_for_skeletons(self, list_of_skeletons):
        results = []
        for skel in list_of_skeletons:
            mp, angle = self.get_midpoint_and_perp_angle(skel)
            if mp is not None:
                results.append((mp, angle))
        return results

    def draw_midpoints_and_perp_angles(self, image, midpoints_and_perp_angles):
        draw = image.copy()
        for mp, angle in midpoints_and_perp_angles:
            (mr, mc) = mp
            cv2.circle(draw, (mc, mr), 5, (0, 0, 255), -1)
            length = 60
            dx = int(length * math.cos(angle * math.pi / 180.0))
            dy = int(length * math.sin(angle * math.pi / 180.0))
            end_x = mc + dx
            end_y = mr + dy
            cv2.arrowedLine(draw, (mc, mr), (end_x, end_y), (0, 255, 255), 2, tipLength=0.2)
        return draw

    def convert_skeletons_to_tracking_objects(self, data, contour_size=130, object_type=0):
        infos = []
        if len(data) > 0:
            if isinstance(data[0], tuple):
                midpoints_and_perp_angles = data
                for mp, angle in midpoints_and_perp_angles:
                    obj = []
                    (mr, mc) = mp

                    realPos = self.image_to_conveyor_matrix.map(QPoint(mc, -mr))
                    realWH = self.image_to_real_scale * QPoint(contour_size, contour_size)

                    center_x = realPos.x()
                    center_y = realPos.y()
                    width = round(abs(realWH.x()))
                    length = round(abs(realWH.y()))
                    
                    obj = [center_x, center_y, width, length, -angle, object_type]
                    infos.append(obj)
            elif isinstance(data[0], list):
                return self.convert_objects_to_tracking_objects(
                    data, object_type=object_type, min_width_length=2
                )
        else:
            return []
        # print("infossss:", infos)
        return infos

    def convert_objects_to_tracking_objects(self, objs, object_type=None, min_width_length=2):
        infos = []
        if not objs:
            return infos
        for obj in objs:
            if len(obj) < 4:
                continue
            typ = int(obj[0]) if object_type is None else int(object_type)
            realPos = self.image_to_conveyor_matrix.map(QPoint(obj[1][0], -obj[1][1]))
            realWH = self.image_to_real_scale * QPoint(obj[2][0], obj[2][1])
            center_x = realPos.x()
            center_y = realPos.y()
            width = round(abs(realWH.x()))
            length = round(abs(realWH.y()))
            if width < min_width_length or length < min_width_length:
                continue
            angle = obj[3]
            infos.append([center_x, center_y, width, length, angle, typ])
        return infos

    def push_tracking_objects(self, tracking_objects, _min = None, _max = None):
        self.tracking_objs = []
        if len(tracking_objects) > 0:
            # Lọc theo kích thước nếu có min/max
            if _min is not None or _max is not None:
                filtered_objects = []
                for obj in tracking_objects:
                    # obj = [center_x, center_y, width, length, angle, type]
                    width = obj[2]
                    length = obj[3]
                    
                    # Kiểm tra min
                    if _min is not None and (width < _min or length < _min):
                        continue
                    
                    # Kiểm tra max
                    if _max is not None and (width > _max or length > _max):
                        continue
                    
                    filtered_objects.append(obj)
                
                if len(filtered_objects) > 0:
                    self.tracking_objs = filtered_objects
                    self.detected.emit(filtered_objects)
            else:
                self.tracking_objs = tracking_objects
                self.detected.emit(tracking_objects)
            # print("tracking_objects:", tracking_objects)

    def detect_with_custom_rknn(self, image):
        __begin = time.time()
        boxes, scores, masks = testrknn.detect_image_rknn(self.custom_rknn, image, conf_thresh=0.4, iou_thresh=0.45)
        
        skeletons = testrknn.get_skeletons_from_masks(masks)
        midpoints_and_perp_angles = self.get_midpoints_and_perp_angles_for_skeletons(skeletons)
        tracking_objects = self.convert_skeletons_to_tracking_objects(midpoints_and_perp_angles)
        __end = time.time()
        # print("Thời gian detect =", __end - __begin)
        self.push_tracking_objects(tracking_objects)
        return self.draw_midpoints_and_perp_angles(image, midpoints_and_perp_angles)

    def request_camera_image(self, state, image_type):
        self.is_request_camera_image = state
        self.request_camera_image_type = image_type

    def send_request_camera_image(self):
        if self.request_camera_image_type == 'original':
            self.send_request_camera_image_signal.emit(self.request_camera_image_type, self.origin_image)
        elif self.request_camera_image_type == 'wrapped':
            self.send_request_camera_image_signal.emit(self.request_camera_image_type, self.wrap_image)
        elif self.request_camera_image_type == 'cropped':
            self.send_request_camera_image_signal.emit(self.request_camera_image_type, self.detecting_image)




    def crop_template_image(self, image_name, project_name, x, y, w, h):
        """Crop ảnh template trực tiếp từ file gốc, lưu lại và reload danh sách template"""
        try:
            if not image_name:
                raise ValueError("image_name is required")
            if w <= 0 or h <= 0:
                raise ValueError(f"Invalid crop dimensions: w={w}, h={h}")

            file_path = os.path.join("templates", project_name, image_name)
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Image not found: {file_path}")

            img = cv2.imread(file_path)
            if img is None:
                raise IOError(f"Failed to read image: {file_path}")

            img_h, img_w = img.shape[:2]
            x = max(0, min(x, img_w - 1))
            y = max(0, min(y, img_h - 1))
            w = max(1, min(w, img_w - x))
            h = max(1, min(h, img_h - y))

            cropped = img[y:y + h, x:x + w]
            cv2.imwrite(file_path, cropped)
            print(f"[VisionTool] Cropped '{image_name}' ({x},{y},{w},{h}) → saved to {file_path}")

            # Reload lại danh sách template sau khi cắt
            self.load_system_settings()

            self.crop_template_image_done.emit(True, image_name, project_name, '')
        except Exception as e:
            print(f"[VisionTool] crop_template_image error: {e}")
            self.crop_template_image_done.emit(False, image_name, project_name, str(e))


if __name__ == "__main__":
    pass
