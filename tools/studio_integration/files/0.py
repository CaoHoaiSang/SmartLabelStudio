from PySide6.QtCore import QObject, Signal as pyqtSignal, QByteArray, QSettings
from PySide6.QtNetwork import QTcpServer, QTcpSocket, QHostAddress
from LogManager import log_error, log_system, LogModule, LogLevel, LogAction
import numpy as np
import VariableManager
import time
import os
import glob
import platform
import subprocess
import cv2
import math
import json
from collections import deque
from utils import xyxyxyxy2xywhdeg, pixelRBoxes2percentRBoxes

# Only import YOLORKNN on Linux
if platform.system() == "Linux":
    try:
        from YOLORKNN import YOLORKNN, Task
        from YOLORKNN.result.resultConverter import JSONResultConverter
        USE_YOLORKNN = True
    except ImportError:
        try:
            from YOLOHailo import YoloHailo, Task
            from YOLOHailo.result.resultConverter import JSONResultConverter
            USE_YOLORKNN = False
        except ImportError:
            print("Error: Neither YOLORKNN nor YOLOHailo could be imported")
            USE_YOLORKNN = None

elif platform.system() == "Windows":
    try:
        from ultralytics import YOLO
        USE_YOLOCUSTOM = True
    except ImportError:
        try:
            from ultralytics import YOLO
            USE_YOLOCUSTOM = False
        except ImportError:
            print("Error: Neither YOLORUSE_YOLOCUSTOMKNN  could be imported")
            USE_YOLOCUSTOM = None
class YoloPredict:
    def __init__(self, model_path,  conf = 0.7, iou=0.1):
        self.model_path = model_path
        self.conf = conf
        self.iou = iou
        self.load_model()
         
    def load_model(self):
        try:            
            self.model = YOLO(self.model_path)
            print("YOLO: model Loaded")
        except Exception as e:
            print(f"Error loading model: {e}")
            return False
        return True
        
    def predict_skeleton(self, image, save=False):
        # start_time = time.time()
        results = self.model(source=image, verbose=False, save=save , conf= self.conf, iou=self.iou)
        mask, cls = self.get_mask_infos(results=results, image=image)
        # print(f"Time taken: {time.time() - start_time} seconds")
        return mask, cls
    
    def predict(self, image, save=False):
       
        results = self.model(source=image, verbose=False, save=save , conf= self.conf, iou=self.iou)
        if self._num_detections(results) == 0:
            return [], image
         # print(f"Time taken: {time.time() - start_time} seconds")
        return results, image  

    def _num_detections(self, results) -> int:
        try:
            # Ultralytics YOLOv8: list[Results]
            if isinstance(results, (list, tuple)) and results:
                r0 = results[0]
                if hasattr(r0, "boxes") and r0.boxes is not None:
                    try:
                        return len(r0.boxes)                   # Boxes thường hỗ trợ __len__
                    except TypeError:
                        if hasattr(r0.boxes, "data"):
                            return int(getattr(r0.boxes, "data").shape[0])
                if hasattr(r0, "masks") and r0.masks is not None:
                    return len(r0.masks)
                
                if hasattr(r0, "obb") and r0.obb is not None:
                    try:
                        print("length", len(r0.obb))
                        return len(r0.obb)                   # OBB thường hỗ trợ __len__
                    except TypeError:
                        if hasattr(r0.obb, "data"):
                            return int(getattr(r0.obb, "data").shape[0])

                # Trường hợp list chứa dict kiểu bạn đã đưa: {'type':'seg','data':[...]}
                if isinstance(r0, dict):
                    return len(r0.get("data", []))

            # YOLOv5 style
            if hasattr(results, "pred"):
                return len(results.pred[0])

            # Kết quả dạng dict thuần
            if isinstance(results, dict):
                if "data" in results:
                    return len(results["data"])
                if "boxes" in results:
                    return len(results["boxes"])
        except Exception:
            pass
        return 0

class SocketCommand(QObject):
    stateChanged = pyqtSignal(bool)

    def __init__(self, host=None, port=None):
        super().__init__()
        self.host = host
        self.port = port
        self.input_data = QByteArray()

    def open(self):
        self.server_socket = QTcpServer()
        
        ret = self.server_socket.listen(QHostAddress(self.host), self.port)
        self.server_socket.newConnection.connect(self.handle_new_connection)
        self.clients = []
        
        if ret == True:
            print("Listening {0}:{1}".format(self.host, self.port))
        else:
            print("Fail to open server\n")

    def handle_new_connection(self):
        client = self.server_socket.nextPendingConnection()
        client.readyRead.connect(self.handle_client_data)
        self.clients.append(client)

    def handle_client_data(self):
        client = self.sender()
        if type(client) == QTcpSocket:
            time_sleep = 0
            max_wait = 100  # Maximum wait time in ms
            while not client.canReadLine():
                self.thread().msleep(5)
                time_sleep += 1
                if time_sleep >= max_wait:
                    print("Timeout waiting for client data")
                    break

            if time_sleep >= max_wait:
                return

            self.input_data += client.readAll()

            if self.input_data == "ExternalScript\n":
                self.send_msg_to_clients("deltax".encode())
                self.input_data.clear()
                self.stateChanged.emit(True)
                return

            if self.input_data.indexOf('\n') > 6:
                self.process_object_infos(self.input_data.data().decode())
                self.input_data.clear()

    def process_object_infos(self, data):
        pass

    def send_msg_to_clients(self, data):
        size = -1
        disconnected_clients = []
        
        for client in self.clients:
            try:
                size = client.write(data)
                client.flush()
            except Exception as e:
                print(f"Error sending data to client: {e}")
                disconnected_clients.append(client)
        
        # Remove disconnected clients
        for client in disconnected_clients:
            if client in self.clients:
                self.clients.remove(client)
                client.disconnectFromHost()
        
        return size

class ImageServer(QObject):
    got_objects = pyqtSignal(list)
    models_list_updated = pyqtSignal(list)
    aix_error_signal = pyqtSignal(str)

    def __init__(self):
        QObject.__init__(self)
        self.models_dir = "models"
        self.model_list = []
        self.clients = []  # Initialize clients list

        self.is_has_request_save_annotations = False
        self.requested_save_file_path = None
        self.annotation_buffer = []

        self.load_aix_infor()

    def scan_models(self):
        """Scan the models directory for model files"""
        if platform.system() == "Linux":
            try:
                if not os.path.exists(self.models_dir):
                    os.makedirs(self.models_dir)
                    
                # Use correct extension based on library
                extension = ".rknn" if USE_YOLORKNN else ".hef"
                model_files = glob.glob(os.path.join(self.models_dir, f"*{extension}"))
                self.model_list = [os.path.splitext(os.path.basename(model))[0] for model in model_files]
                print(f"- Found {len(self.model_list)} {extension.upper()} models: {self.model_list}")
                self.models_list_updated.emit(self.model_list)
                return self.model_list
            except Exception as e:
                print(f"Error scanning models directory: {e}")
                return []
        else:
            try:
                models_dir = "models"
                if not os.path.exists(models_dir):
                    print(f"Models directory not found: {models_dir}")
                    return []

                # Get all subdirectories in deltax_models
                model_folders = [f for f in os.listdir(models_dir) if os.path.isdir(os.path.join(models_dir, f))]
                
                # Check each folder for .imwi files and validate model structure
                self.model_list = []
                extension = ".pt"  
                model_files = glob.glob(os.path.join(models_dir, f"*{extension}"))
                self.model_list = [os.path.splitext(os.path.basename(model))[0] for model in model_files]
 
                print(f"- Found {len(self.model_list)} valid Windows models: {self.model_list}")
                self.models_list_updated.emit(self.model_list)
                return self.model_list
            except Exception as e:
                print(f"Error scanning Windows models directory: {e}")
                return []

    def delete_model(self, model_name):
        if platform.system() == "Linux":
            try:
                model_path = os.path.join(self.models_dir, f"{model_name}.rknn")
                
                if not os.path.exists(model_path):
                    print(f"Model file not found: {model_path}")
                    return False
                
                if hasattr(self, 'aix_project_name') and model_name == self.aix_project_name:
                    print(f"Model {model_name} is currently in use, disconnecting before deletion")
                    self.disconnect()
                    
                    remaining_models = [m for m in self.model_list if m != model_name]
                    if remaining_models:
                        self.aix_project_name = remaining_models[0]
                        print(f"Switching to alternative model: {self.aix_project_name}")
                        restart_needed = True
                    else:
                        print("No alternative models available after deletion")
                        restart_needed = False
                else:
                    restart_needed = False
                    
                os.remove(model_path)
                print(f"Model file deleted: {model_path}")
                
                if restart_needed:
                    self.start_aix()
                else:
                    self.scan_models()
                
                return True
            except Exception as e:
                print(f"Error deleting model file: {e}")
                return False
        else:
            try:
                current_path = os.path.dirname(os.path.abspath(__file__))
                model_path = os.path.join(current_path, "deltax_models", model_name)
                
                if not os.path.exists(model_path):
                    print(f"Model directory not found: {model_path}")
                    return False
                
                if hasattr(self, 'aix_project_name') and model_name == self.aix_project_name:
                    print(f"Model {model_name} is currently in use, disconnecting before deletion")
                    self.disconnect()
                    
                    remaining_models = [m for m in self.model_list if m != model_name]
                    if remaining_models:
                        self.aix_project_name = remaining_models[0]
                        print(f"Switching to alternative model: {self.aix_project_name}")
                        restart_needed = True
                    else:
                        print("No alternative models available after deletion")
                        restart_needed = False
                else:
                    restart_needed = False
                
                # Delete all files in the model directory
                for file in os.listdir(model_path):
                    file_path = os.path.join(model_path, file)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                    except Exception as e:
                        print(f"Error deleting file {file_path}: {e}")
                
                # Remove the model directory
                os.rmdir(model_path)
                print(f"Model directory deleted: {model_path}")
                
                if restart_needed:
                    self.start_aix()
                else:
                    self.scan_models()
                
                return True
            except Exception as e:
                print(f"Error deleting model directory: {e}")
                return False

    def load_aix_infor(self):
        try:
            self.aix_project_name = str(VariableManager.instance.get("aix.project_name", "cherry"))
            self.aix_list_objects = [obj.strip() for obj in str(VariableManager.instance.get("aix.list_objects", "red,brown,black")).split(',')]
            self.label_type = str(VariableManager.instance.get("aix.label_type", "Detect"))
            self.enabled = bool(int(VariableManager.instance.get("aix.enabled", "1")))
            self.model_type = str(VariableManager.instance.get("aix.model_type", "DET"))
            self.conf = float(VariableManager.instance.get("aix.conf", 0.4))
            self.iou = float(VariableManager.instance.get("aix.iou", 0.4))
            self.aix_class_confidence_map = {}
            raw_class_confidence_map = VariableManager.instance.get("aix.class_confidence_map", "{}")
            parsed_class_confidence_map = raw_class_confidence_map if isinstance(raw_class_confidence_map, dict) else json.loads(str(raw_class_confidence_map))
            if isinstance(parsed_class_confidence_map, dict):
                for key, value in parsed_class_confidence_map.items():
                    try:
                        conf_value = float(value)
                    except (TypeError, ValueError):
                        continue
                    self.aix_class_confidence_map[str(key).strip()] = max(0.0, min(1.0, conf_value))

            
        except Exception as e:
            print(f"Error loading aix information: {e}")
            self.aix_class_confidence_map = {}
            
        print(f"- AIX Project Name: {self.aix_project_name}")
        print(f"- AIX List Objects: {self.aix_list_objects}")
        print(f"- AIX Enabled: {self.enabled}")
        print(f"- AIX Model Type: {self.model_type}")

    def _get_conf_threshold(self, object_name_or_id):
        default_conf = max(0.0, min(1.0, float(getattr(self, 'conf', 0.4))))
        class_conf_map = getattr(self, 'aix_class_confidence_map', {})
        if not isinstance(class_conf_map, dict):
            return default_conf

        keys_to_try = []
        object_key = str(object_name_or_id).strip()
        if object_key != "":
            keys_to_try.append(object_key)

        try:
            class_index = int(float(object_name_or_id))
            keys_to_try.append(str(class_index))
            if 0 <= class_index < len(self.aix_list_objects):
                mapped_name = str(self.aix_list_objects[class_index]).strip()
                if mapped_name != "":
                    keys_to_try.append(mapped_name)
        except Exception:
            pass

        # Preserve order while removing duplicates
        keys_to_try = list(dict.fromkeys(keys_to_try))
        for key in keys_to_try:
            if key in class_conf_map:
                try:
                    return max(0.0, min(1.0, float(class_conf_map[key])))
                except (TypeError, ValueError):
                    continue

        return default_conf

    def reconnect(self, project_name=None, list_objects=None):
        self.enabled = bool(int(VariableManager.instance.get("aix.enabled", "1")))
        old_project_name = getattr(self, 'aix_project_name', None)
        old_list_objects = list(getattr(self, 'aix_list_objects', []))
        self.load_aix_infor()

        if hasattr(self, 'model'):
            if hasattr(self.model, 'conf'):
                self.model.conf = self.conf
            if hasattr(self.model, 'iou'):
                self.model.iou = self.iou

        if not self.enabled:
            self.disconnect()
            return

        if platform.system() == "Linux":
            print("- Checking AIX model settings...")
            
            project_changed = False
            if old_project_name != self.aix_project_name:
                project_changed = True
                print(f"- New AIX Project Name: {self.aix_project_name}")
                
            objects_changed = False
            if old_list_objects != self.aix_list_objects:
                objects_changed = True
                print(f"- New AIX List Objects: {self.aix_list_objects}")
            
            if project_changed or objects_changed:
                print("- Reconnecting AIX model due to setting changes...")
                self.disconnect()
                self.start_aix()
                return True
            else:
                print("- No changes in AIX settings, keeping current model")
                if not hasattr(self, 'model'):
                    self.start_aix()
                return False
        else:
            print("- Checking Windows AIX model settings...")
            
            project_changed = old_project_name != self.aix_project_name
            if project_changed:
                print(f"- New AIX Project Name: {self.aix_project_name}")
            
            if project_changed:
                print("- Reconnecting Windows AIX model due to setting changes...")
                self.disconnect()
                self.start_aix()
                return True
            else:
                print("- No changes in AIX settings, keeping current model")
                if not hasattr(self, 'model'):
                    self.start_aix()
                return False

    def start_aix(self):
        self.scan_models()

        if not self.enabled:
            return
        
        if platform.system() == "Linux":
            try:

                # Use correct extension based on library
                extension = ".rknn" if USE_YOLORKNN else ".hef"
                model_path = os.path.join(self.models_dir, f"{self.aix_project_name}{extension}")
                if not os.path.exists(model_path):
                    error_msg = f"Error: Model file {model_path} not found!"
                    print(error_msg)
                    if self.model_list:
                        self.aix_project_name = self.model_list[0]
                        model_path = os.path.join(self.models_dir, f"{self.aix_project_name}{extension}")
                        print(f"Using alternative model: {model_path}")
                    else:
                        error_msg = f"No models available! Please add {extension.upper()} models to the models directory."
                        print(error_msg)
                        log_error(LogModule.AIX, LogLevel.ERROR, f"Error: Model file {model_path} not found!")
                        self.aix_error_signal.emit(error_msg)
                        return
                    
                print(f"Loading model: {model_path}")

                task = Task.DET
                if self.model_type == "OBB":
                    task = Task.OBB
                elif self.model_type == "ORI":
                    task = Task.ORI
                elif self.model_type == "SEG":
                    task = Task.SEG
                
                if USE_YOLORKNN:
                    self.model = YOLORKNN(
                        task,
                        model_path, 
                        self.aix_list_objects, 
                        iou = self.iou,
                        conf = self.conf
                    )
                else:
                    self.model = YoloHailo(
                        Task.DET,
                        model_path, 
                        self.aix_list_objects, 
                        iou = self.iou,
                        conf = self.conf
                    )
                print("Model loaded successfully!")
                log_system(LogModule.AIX, LogAction.INITIALIZED, "AIX model initialized successfully: " + model_path)
            except Exception as e:
                del self.model
                error_msg = f"Error initializing AIX model: {str(e)}"
                print(error_msg)
                log_error(LogModule.AIX, LogLevel.ERROR, f"Error initializing AIX model: {str(e)}")
                self.aix_error_signal.emit(error_msg)
                return
        else:
            try:
                print("load model")
                models_dir = "models"
                # Use correct extension based on library
                extension = ".pt" 
                model_path = os.path.join(models_dir, f"{self.aix_project_name}{extension}")
                if not os.path.exists(model_path):
                    error_msg = f"Error: Model file {model_path} not found!"
                    print(error_msg)
                    if self.model_list:
                        self.aix_project_name = self.model_list[0]
                        model_path = os.path.join(models_dir, f"{self.aix_project_name}{extension}")
                        print(f"Using alternative model: {model_path}")
                    else:
                        error_msg = f"No models available! Please add {extension.upper()} models to the models directory."
                        print(error_msg)
                        log_error(LogModule.AIX, LogLevel.ERROR, f"Error: Model file {model_path} not found!")
                        self.aix_error_signal.emit(error_msg)
                        return
                    
                print(f"Loading model: {model_path}")
                self.model = YoloPredict(model_path, conf= self.conf, iou=self.iou)
          
                print("Model loaded successfully!")
                log_system(LogModule.AIX, LogAction.INITIALIZED, "AIX model initialized successfully: " + model_path)
  
                
            except Exception as e:
                error_msg = f"Error initializing AIX process: {str(e)}"
                print(error_msg)
                log_error(LogModule.AIX, LogLevel.ERROR, f"Error initializing AIX process: {str(e)}")
                self.aix_error_signal.emit(error_msg)
                return

    def disconnect(self):
        if hasattr(self, 'model'):
            print("- Disconnecting existing AIX model")
            del self.model

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
 

    def process_object_infos(self, data, width=None, height=None):
        if platform.system() == "Linux":
            infos = []
            list_objects = data['data']
            for item in list_objects:
                name = item['name']
                x = item['x']
                y = item['y']
                w = item['w']
                h = item['h']
                conf = float(item['conf'])

                if conf < self._get_conf_threshold(name):
                    continue

                # ORI supplies directed degrees; legacy OBB JSON supplies radians.
                if 'deg' in item:
                    deg = float(item['deg'])
                elif data.get('type') == 'obb' and 'angle' in item:
                    deg = math.degrees(float(item['angle']))
                else:
                    deg = 0.0
                if not math.isfinite(deg):
                    continue

                if self.model_type != "SEG" and self.is_rotated_box_touching_edge(x, y, w, h, deg, width, height):
                    continue

                obj_type = name
                for i in range(len(self.aix_list_objects)):
                    if obj_type == self.aix_list_objects[i]:
                        obj_type = i
                        break

                if self.is_has_request_save_annotations and self.model_type != "SEG":
                    info_annotation = {}
                    info_annotation['type'] = obj_type
                    info_annotation['x'] = x 
                    info_annotation['y'] = y
                    info_annotation['w'] = w
                    info_annotation['h'] = h
                    info_annotation['deg'] = deg
                    self.annotation_buffer.append(info_annotation)

                info = []
                info.append(obj_type)  #(id)
                info.append((x, y)) #(x, y)
                info.append((w, h)) #(w, h)
                info.append(-deg)
                info.append(conf)
                infos.append(info)

            self.got_objects.emit(infos)

        else:
            infos = []
            if isinstance(data[0], dict) == True:
                for objs in data:

                    obj = objs["data"][0]
                    name   = obj["name"]
                    x, y   = obj["x"], obj["y"]
                    w, h   = obj["w"], obj["h"]
                    conf   = float(obj["conf"])
                    angle   = obj["angle"]

                    if conf < self._get_conf_threshold(name):
                        continue

                    if self.is_rotated_box_touching_edge(x, y, w, h, angle, width, height):
                        continue
    
                    obj_type = name
                    for i in range(len(self.aix_list_objects)):
                        if obj_type == self.aix_list_objects[i]:
                            obj_type = i
                            break

                    info = []
                    info.append(obj_type)  #(id)
                    info.append((int(x), int(y))) #(x, y)
                    info.append((int(w), int(h))) #(w, h)
                    info.append(-angle)
                    info.append(conf)
                    infos.append(info)

            else:
                for dt in data:

                    name = dt[0]
                    x= dt[1][0]
                    y= dt[1][1]
                    w= dt[2][0]
                    h= dt[2][1]
                    deg = dt[3]
                    conf = None
                    if len(dt) > 4:
                        try:
                            conf = float(dt[4])
                        except (TypeError, ValueError):
                            conf = None

                    if conf is not None and conf < self._get_conf_threshold(name):
                        continue
                    
                    if self.is_rotated_box_touching_edge(x, y, w, h, deg, width, height):
                        continue

                    obj_type = name
                    for i in range(len(self.aix_list_objects)):
                        if obj_type == self.aix_list_objects[i]:
                            obj_type = i
                            break

                    info = []
                    info.append(obj_type)  #(id)
                    info.append((int(x), int(y))) #(x, y)
                    info.append((int(w), int(h))) #(w, h)
                    info.append(-deg)
                    info.append(conf)
                    infos.append(info)
            # print("Detected:", infos)
            self.got_objects.emit(infos)
           
    def send_image(self, input:np.ndarray):
        if not self.enabled:
            return

        if platform.system() == "Linux":
            if not hasattr(self, 'model'):
                print("Model not initialized!")
                return
            try:
                result = self.model.inference(input)
                if self.model_type == "SEG":
                    json_data = self.box_in_seg_linux(result, image_width=input.shape[1], image_height=input.shape[0])
                else:
                    json_data = result.to(JSONResultConverter())
                self.process_object_infos(json_data, width=input.shape[1], height=input.shape[0])

                if self.is_has_request_save_annotations:
                    self.save_annotations_to_file(image_width=input.shape[1], image_height=input.shape[0])
            except Exception as e:
                error_message = str(e)

                if "broadcast" in error_message:
                    self.aix_error_signal.emit("Please change type of box in model")
                elif "reshape" in error_message:
                    self.aix_error_signal.emit("Please change number of classes")
                else:
                    self.aix_error_signal.emit("Unknown error")
        else:
    
            results, _ = self.model.predict(input, save=True)
            if len(results) == 0:
                print("No objects detected")
                self.got_objects.emit([])
                return
            infos, _ = self.get_box_infos(results=results, image=input, box_type=self.model_type, image_width=input.shape[1], image_height=input.shape[0])
            self.process_object_infos(infos, width=input.shape[1], height=input.shape[0])

    def box_in_seg_linux(self, result, image_width=None, image_height=None):
    
        if result.masks is None:
            # print("No masks detected")
            return {"type": "seg", "data": []}
        
        masks = result.masks.xy
        confs = result.boxes.conf
        cls_indices = result.boxes.cls  # Class index for each detection
        names = result.names  # List of class names

        data_list = []
        if masks is not None and cls_indices is not None and confs is not None:
            for mask, cls_idx, conf in zip(masks, cls_indices, confs):
                
                mask_np = np.array(mask, dtype=np.int32)
                rect = cv2.minAreaRect(mask_np)
                (cx, cy), (width, height), angle = rect

                if self.is_rotated_box_touching_edge(cx, cy, width, height, angle, image_width, image_height):
                    continue

                if height < width:
                    width, height = height, width
                    # Điều chỉnh góc: thêm 90 độ khi đảo
                    angle = angle + 90
                    angle = int(angle % 180)

                # Get class name from index
                obj_type = names[int(cls_idx)]

                if self.is_has_request_save_annotations:
                    info_annotation = {}
                    info_annotation['type'] = int(cls_idx)
                    info_annotation['seg'] = mask_np.tolist()
                    self.annotation_buffer.append(info_annotation)
    
                data_list.append({
                    "name": obj_type,
                    "y": cy,         
                    "w": width,         
                    "x": cx,         
                    "h": height,
                    "deg": angle,
                    "conf": float(conf),
                    "points": mask_np.tolist()
                })
                
        return {"type": "seg", "data": data_list}
        
    def get_box_infos(self, results, image , box_type:str, image_width=None, image_height=None): 
        infos = []
        if box_type == "ORI":
            infos = []
            for result in results:
                boxs = result.obb.xywhr
                names = [result.names[cls.item()] for cls in result.obb.cls.int()]  # class name of each box
                confs = result.obb.conf  # confidence score of each box

                for box, name, conf in zip(boxs, names, confs):
                    np_box = box.cpu().detach().numpy()
                    cx = int(np_box[0])
                    cy = int(np_box[1])
                    width = int(np_box[2])
                    height = int(np_box[3])
                    conf_value = float(conf)
    
                    r = (int(np_box[4] * 180/np.pi) )
                    if r < -180:
                        r =  360 + r
                    
                    if conf_value < self._get_conf_threshold(name):
                        continue

                    obj_type = name

                    info = []
                    info.append(obj_type)  #(id)
                    info.append((cx, cy)) #(x, y)
                    info.append((width,height)) #(w, h)
                    info.append(r)
                    info.append(conf_value)

                    infos.append(info)
 
            return infos, image
        elif box_type == "DET":
            for result in results:
                rss = result.boxes.data.cpu().numpy()
                for rs in rss:
                    x1 = rs[0]
                    y1 = rs[1]
                    x2 = rs[2]
                    y2 = rs[3]
                    conf = rs[4]
                    name = rs[5]
                    conf_value = float(conf)

                    center_x = int((x1 + x2) / 2)
                    center_y = int((y1 + y2) / 2)
                    w = int(x2 - x1)
                    h = int(y2 - y1)

                    if conf_value < self._get_conf_threshold(name):
                        continue

                    obj_type = name

                    info = []
                    info.append(int(obj_type))  #(id)
                    info.append((int(center_x), int(center_y))) #(x, y)
                    info.append((int(w), int(h))) #(w, h)
                    info.append(0)
                    info.append(conf_value)
                    infos.append(info)
        
            return infos, image
        elif box_type == "SEG":
            for result in results:
                masks = result.masks.xy
                names = result.boxes.cls.cpu().numpy()
                confs = result.boxes.conf.cpu().numpy()

                infos = []
                if masks is not None and names is not None and confs is not None:
                    for mask, name, conf in zip(masks, names, confs):
                        conf_value = float(conf)
                        if conf_value < self._get_conf_threshold(name):
                            continue
            
                        # mask: (N, 2) array of polygon points
                        mask_np = np.array(mask, dtype=np.int32)
                        rect = cv2.minAreaRect(mask_np)
                        (cx, cy), (width, height), angle = rect

                        if self.is_rotated_box_touching_edge(cx, cy, width, height, angle, image_width, image_height):
                            continue

                        if height < width:
                            width, height = height, width
                            # Điều chỉnh góc: thêm 90 độ khi đảo
                            angle = angle + 90
                            angle = int(angle % 180)

                        obj_type = name
 
            
                        info = {
                            "type": "seg",
                            "data": [
                                {
                                "name": obj_type,
                                "y": cy,         
                                "w": width,         
                                "x": cx,         
                                "h": height,
                                "angle": angle,
                                "conf": conf_value,
                                "points": mask_np.tolist()  # Convert numpy array to list  
                                }
                            ]
                            }
                        
                        infos.append(info)
                return infos, image
            
    def request_save_annotations(self, file_path):
        self.is_has_request_save_annotations = True
        self.requested_save_file_path = file_path
            
    def save_annotations_to_file(self, image_width, image_height):
        """Save annotations from annotation_buffer to label file with normalized coordinates"""
        try:
            if not self.annotation_buffer:
                print("No annotations to save")
                return False
            
            with open(self.requested_save_file_path, 'w') as f:
                for annotation in self.annotation_buffer:
                    class_id = annotation['type']
                    
                    if self.model_type == "SEG":
                        # SEG: id x1_norm y1_norm x2_norm y2_norm x3_norm y3_norm ...
                        # annotation['seg'] contains list of [x, y] points
                        seg_points = annotation['seg']
                        normalized_points = []
                        for point in seg_points:
                            x_norm = point[0] / image_width
                            y_norm = point[1] / image_height
                            normalized_points.extend([f"{x_norm:.6f}", f"{y_norm:.6f}"])
                        
                        points_str = ' '.join(normalized_points)
                        f.write(f"{class_id} {points_str}\n")
                        
                    elif self.model_type in ["OBB", "ORI"]:
                        # OBB/ORI: id x_center_norm y_center_norm width_norm height_norm angle
                        x = annotation['x']
                        y = annotation['y']
                        w = annotation['w']
                        h = annotation['h']
                        deg = annotation['deg']
                        
                        # Use pixelRBoxes2percentRBoxes for proper rotated box normalization
                        # Input format: [[cx, cy, w, h, angle]]
                        rbox_pixel = np.asarray([[x, y, w, h, deg]], dtype=np.float32)
                        rbox_normalized = pixelRBoxes2percentRBoxes(rbox_pixel, image_width, image_height)
                        x_norm, y_norm, w_norm, h_norm, angle_norm = rbox_normalized[0]
                        
                        f.write(f"{class_id} {x_norm:.6f} {y_norm:.6f} {w_norm:.6f} {h_norm:.6f} {angle_norm:.2f}\n")
                        
                    else:  # DET
                        # DET: id x_center_norm y_center_norm width_norm height_norm
                        x = annotation['x']
                        y = annotation['y']
                        w = annotation['w']
                        h = annotation['h']
                        
                        # Normalize by image dimensions
                        x_norm = x / image_width
                        y_norm = y / image_height
                        w_norm = w / image_width
                        h_norm = h / image_height
                        
                        f.write(f"{class_id} {x_norm:.6f} {y_norm:.6f} {w_norm:.6f} {h_norm:.6f}\n")
            
            # print(f"Saved {len(self.annotation_buffer)} annotations to {file_path}")
            # Clear buffer after saving
            self.annotation_buffer = []
            self.is_has_request_save_annotations = False
            self.requested_save_file_path = None
            
            return True
        except Exception as e:
            print(f"Error saving annotations: {e}")
            return False

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
            mp, angle = self.get_midpoint_and_perp_angle(skel[0])
            if mp is not None:
                results.append((tuple(map(int, mp)), angle, skel[1]))
        return results

    
    def draw_midpoints_and_perp_angles(self, image, midpoints_and_perp_angles):
        draw = image.copy()
        for mp, angle, _ in midpoints_and_perp_angles:
            (mr, mc) = mp
            cv2.circle(draw, (mc, mr), 5, (0, 0, 255), -1)
            length = 60
            dx = int(length * math.cos(angle * math.pi / 180.0))
            dy = int(length * math.sin(angle * math.pi / 180.0))
            end_x = mc + dx
            end_y = mr + dy
            cv2.arrowedLine(draw, (mc, mr), (end_x, end_y), (0, 255, 255), 2, tipLength=0.2)

        cv2.imwrite("img_draw.jpg", draw)
        return draw
