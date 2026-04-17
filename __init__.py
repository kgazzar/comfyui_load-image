import os
import shutil
import hashlib
import torch, numpy as np
from PIL import Image, ImageOps
from server import PromptServer
from aiohttp import web
import folder_paths

# 1. API لجلب أسماء الصور والمجلدات الفرعية
@PromptServer.instance.routes.post("/custom_folder/get_images")
async def get_images(request):
    data = await request.json()
    # تنظيف المسار من أي مسافات أو علامات تنصيص لتجنب أخطاء الويندوز
    folder = data.get("folder", "").strip().strip('"').strip("'")
    if not os.path.exists(folder) or not os.path.isdir(folder):
        return web.json_response({"images": [], "folders": [], "parent": ""})
    
    valid_ext = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
    try:
        files = []
        folders = []
        for f in sorted(os.listdir(folder)):
            full_path = os.path.join(folder, f)
            if os.path.isdir(full_path):
                folders.append(f)
            elif os.path.isfile(full_path) and os.path.splitext(f)[1].lower() in valid_ext:
                files.append(f)
                
        parent = os.path.abspath(os.path.join(folder, os.pardir))
        if os.path.abspath(folder) == parent or not folder:
            parent = ""  # Root reached
            
        return web.json_response({"images": files, "folders": folders, "parent": parent})
    except Exception as e:
        print(f"Error reading custom folder: {e}")
        return web.json_response({"images": [], "folders": [], "parent": ""})

# 2. API لعمل معاينة فورية في النود
@PromptServer.instance.routes.post("/custom_folder/view_preview")
async def view_preview(request):
    data = await request.json()
    folder = data.get("folder", "").strip().strip('"').strip("'")
    image_name = data.get("image_name", "")
    image_path = os.path.join(folder, image_name)
    
    if not os.path.exists(image_path) or not os.path.isfile(image_path):
        return web.json_response({"filename": ""})
        
    temp_dir = folder_paths.get_temp_directory()
    temp_filename = f"preview_{hashlib.md5(image_path.encode()).hexdigest()}_{image_name}"
    temp_path = os.path.join(temp_dir, temp_filename)
    
    try:
        if not os.path.exists(temp_path):
            shutil.copy2(image_path, temp_path)
        return web.json_response({"filename": temp_filename})
    except Exception:
        return web.json_response({"filename": ""})

# 3. API جديد لخدمة الصور مباشرة لشبكة الجريد (بدون حفظ في Temp)
@PromptServer.instance.routes.get("/custom_folder/view_image")
async def view_image(request):
    folder = request.query.get("folder", "").strip().strip('"').strip("'")
    filename = request.query.get("filename", "")
    file_path = os.path.join(folder, filename)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return web.FileResponse(file_path)
    return web.Response(status=404)

# 4. كود النود الأساسي
class LoadImageFromCustomFolder:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "folder_path": ("STRING", {"default": "C:/", "multiline": False}),
                "image_name": (["Enter folder path first..."], )
            },
            "optional": {
                "index": ("INT", {"default": -1, "min": -1, "max": 999999, "step": 1})
            }
        }
    
    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "load_image"
    CATEGORY = "image"

    @classmethod
    def VALIDATE_INPUTS(s, folder_path, image_name, index=-1):
        return True

    def load_image(self, folder_path, image_name, index=-1):
        folder_path = folder_path.strip().strip('"').strip("'")
        if index >= 0 and os.path.exists(folder_path):
            valid_ext = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
            files = sorted([f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f)) and os.path.splitext(f)[1].lower() in valid_ext])
            if files and 0 <= index < len(files):
                image_name = files[index]

        image_path = os.path.join(folder_path, image_name)
        
        if not os.path.exists(image_path) or not os.path.isfile(image_path):
            img = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            mask = torch.zeros((1, 64, 64), dtype=torch.float32)
            return {"ui": {"images": []}, "result": (img, mask)}
            
        i = ImageOps.exif_transpose(Image.open(image_path))
        image = torch.from_numpy(np.array(i.convert("RGB")).astype(np.float32) / 255.0)[None,]
        if 'A' in i.getbands():
            mask = 1. - torch.from_numpy(np.array(i.getchannel('A')).astype(np.float32) / 255.0)
        else:
            mask = torch.zeros((64,64), dtype=torch.float32)
        
        temp_dir = folder_paths.get_temp_directory()
        temp_filename = f"preview_{hashlib.md5(image_path.encode()).hexdigest()}_{image_name}"
        temp_path = os.path.join(temp_dir, temp_filename)
        try:
            if not os.path.exists(temp_path):
                shutil.copy2(image_path, temp_path)
        except Exception:
            pass
            
        return {"ui": {"images": [{"filename": temp_filename, "subfolder": "", "type": "temp"}]}, "result": (image, mask.unsqueeze(0))}

    @classmethod
    def IS_CHANGED(s, folder_path, image_name, index=-1):
        folder_path = folder_path.strip().strip('"').strip("'")
        if index >= 0 and os.path.exists(folder_path):
            valid_ext = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
            files = sorted([f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f)) and os.path.splitext(f)[1].lower() in valid_ext])
            if files and 0 <= index < len(files):
                image_name = files[index]
                
        image_path = os.path.join(folder_path, image_name)
        if not os.path.exists(image_path):
            return ""
        m = hashlib.sha256()
        with open(image_path, 'rb') as f:
            m.update(f.read())
        return m.digest().hex()

NODE_CLASS_MAPPINGS = {"LoadImageFromCustomFolder": LoadImageFromCustomFolder}
NODE_DISPLAY_NAME_MAPPINGS = {"LoadImageFromCustomFolder": "Load Image (Custom Folder)"}

# 5. التحديث التلقائي للـ JS مع إضافة أزرار النافيجيشن والجريد
js_dir = os.path.join(os.path.dirname(__file__), "js")
if not os.path.exists(js_dir):
    os.makedirs(js_dir)

js_code = """
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
    name: "LoadImageCustomFolder",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name === "LoadImageFromCustomFolder") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) {
                    onNodeCreated.apply(this, arguments);
                }
                
                const node = this;

                // 1. إنشاء الزرار بشكل مباشر لتفادي اختفائه
                this.addWidget("button", "🖼️ Open Image Grid", "grid", async () => {
                    const fWidget = node.widgets.find(w => w.name === "folder_path");
                    let currentNavFolder = fWidget ? fWidget.value : "";
                    
                    if (!currentNavFolder || currentNavFolder === "C:/" || currentNavFolder === "") {
                        alert("Please enter a valid initial folder path.");
                        return;
                    }

                    const gridModal = document.createElement("div");
                    Object.assign(gridModal.style, {
                        position: "fixed", top: "5%", left: "10%", width: "80%", height: "90%",
                        backgroundColor: "#1e1e1e", zIndex: 10000, borderRadius: "10px",
                        display: "flex", flexDirection: "column", padding: "20px",
                        boxShadow: "0 10px 30px rgba(0,0,0,0.8)", color: "white", fontFamily: "sans-serif"
                    });

                    // Header Container
                    const header = document.createElement("div");
                    header.style.display = "flex"; header.style.flexDirection = "column"; header.style.gap = "10px"; header.style.marginBottom = "15px";
                    
                    const topRow = document.createElement("div");
                    topRow.style.display = "flex"; topRow.style.justifyContent = "space-between";
                    const title = document.createElement("h2"); title.innerText = `Folder Explorer`; title.style.margin = "0";
                    const closeBtn = document.createElement("button"); closeBtn.innerText = "❌ Close";
                    Object.assign(closeBtn.style, { padding: "5px 15px", cursor: "pointer", background: "#f44", color: "white", border: "none", borderRadius: "5px", fontWeight: "bold"});
                    closeBtn.onclick = () => { document.body.removeChild(gridModal); };
                    topRow.appendChild(title); topRow.appendChild(closeBtn);
                    
                    // Navigation Row
                    const navRow = document.createElement("div");
                    navRow.style.display = "flex"; navRow.style.gap = "5px"; navRow.style.alignItems = "center";
                    const upBtn = document.createElement("button"); upBtn.innerHTML = "⬆️ Up";
                    Object.assign(upBtn.style, { padding: "8px 15px", cursor: "pointer", background: "#4CAF50", color: "white", border: "none", borderRadius: "5px", fontWeight: "bold"});
                    const pathInput = document.createElement("input"); pathInput.type = "text";
                    Object.assign(pathInput.style, { flexGrow: "1", padding: "8px", borderRadius: "5px", border: "1px solid #555", background: "#333", color: "white" });
                    const goBtn = document.createElement("button"); goBtn.innerText = "Go";
                    Object.assign(goBtn.style, { padding: "8px 15px", cursor: "pointer", background: "#2196F3", color: "white", border: "none", borderRadius: "5px", fontWeight: "bold"});
                    
                    navRow.appendChild(upBtn); navRow.appendChild(pathInput); navRow.appendChild(goBtn);
                    header.appendChild(topRow); header.appendChild(navRow);
                    gridModal.appendChild(header);

                    // Grid Container
                    const gridContainer = document.createElement("div");
                    Object.assign(gridContainer.style, {
                        display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gridAutoRows: "200px",
                        gap: "10px", flexGrow: "1", overflowY: "auto", paddingRight: "10px"
                    });

                    const observer = new IntersectionObserver((entries, obs) => {
                        entries.forEach(entry => {
                            if (entry.isIntersecting && entry.target.dataset.img) {
                                const item = entry.target;
                                const imgName = item.dataset.img;
                                const folderName = item.dataset.folder;
                                item.style.backgroundImage = `url('/custom_folder/view_image?folder=${encodeURIComponent(folderName)}&filename=${encodeURIComponent(imgName)}')`;
                                obs.unobserve(item);
                            }
                        });
                    }, { root: gridContainer, rootMargin: "200px" });

                    const loadFolder = async (targetFolder) => {
                        try {
                            const resp = await api.fetchApi("/custom_folder/get_images", {
                                method: "POST", body: JSON.stringify({ folder: targetFolder })
                            });
                            const data = await resp.json();
                            
                            currentNavFolder = targetFolder;
                            pathInput.value = targetFolder;
                            gridContainer.innerHTML = "";
                            
                            upBtn.disabled = !data.parent;
                            upBtn.style.opacity = data.parent ? "1" : "0.5";
                            upBtn.onclick = () => { if(data.parent) loadFolder(data.parent); };

                            const folders = data.folders || [];
                            const images = data.images || [];
                            
                            title.innerText = `Explorer (${images.length} images)`;

                            // Render Folders
                            folders.forEach(fName => {
                                const item = document.createElement("div");
                                Object.assign(item.style, {
                                    border: "2px solid #555", borderRadius: "5px", cursor: "pointer",
                                    backgroundColor: "#2a2a2a", position: "relative",
                                    display: "flex", alignItems: "center", justifyContent: "center", fontSize: "60px"
                                });
                                item.innerHTML = "📁";
                                item.onmouseover = () => item.style.borderColor = "#4CAF50";
                                item.onmouseout = () => item.style.borderColor = "#555";
                                
                                item.onclick = () => {
                                    const sep = (targetFolder.slice(-1) === "/" || targetFolder.slice(-1) === "\\\\") ? "" : "/";
                                    loadFolder(targetFolder + sep + fName);
                                };

                                const label = document.createElement("div");
                                label.innerText = fName;
                                Object.assign(label.style, {
                                    position: "absolute", bottom: "0", left: "0", right: "0",
                                    backgroundColor: "rgba(0,0,0,0.8)", color: "#4CAF50", fontSize: "14px", fontWeight: "bold",
                                    padding: "4px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", textAlign: "center"
                                });
                                item.appendChild(label);
                                gridContainer.appendChild(item);
                            });

                            // Render Images
                            images.forEach(imgName => {
                                const item = document.createElement("div");
                                item.dataset.img = imgName;
                                item.dataset.folder = targetFolder;
                                Object.assign(item.style, {
                                    border: "2px solid #555", borderRadius: "5px", cursor: "pointer",
                                    backgroundSize: "contain", backgroundPosition: "center", backgroundRepeat: "no-repeat",
                                    backgroundColor: "#000", position: "relative"
                                });
                                item.onmouseover = () => item.style.borderColor = "#fff";
                                item.onmouseout = () => item.style.borderColor = "#555";
                                
                                item.onclick = async () => {
                                    if(fWidget) fWidget.value = targetFolder;
                                    if(node.updateImages) await node.updateImages(imgName);
                                    document.body.removeChild(gridModal);
                                };

                                const label = document.createElement("div");
                                label.innerText = imgName;
                                Object.assign(label.style, {
                                    position: "absolute", bottom: "0", left: "0", right: "0",
                                    backgroundColor: "rgba(0,0,0,0.7)", color: "white", fontSize: "12px",
                                    padding: "4px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", textAlign: "center"
                                });
                                item.appendChild(label);
                                gridContainer.appendChild(item);
                                observer.observe(item);
                            });

                        } catch(e) {
                            console.error("Error loading folder:", e);
                            alert("Error loading folder: " + targetFolder);
                        }
                    };

                    const handleGo = () => { if(pathInput.value.trim()) loadFolder(pathInput.value.trim()); };
                    goBtn.onclick = handleGo;
                    pathInput.onkeydown = (e) => { if(e.key === "Enter") handleGo(); };

                    gridModal.appendChild(gridContainer);
                    document.body.appendChild(gridModal);
                    
                    loadFolder(currentNavFolder);
                });

                // 2. تأخير ربط الوظائف لضمان تحميل الويدجتس الأساسية في ComfyUI
                setTimeout(() => {
                    const folderWidget = node.widgets.find(w => w.name === "folder_path");
                    const imageWidget = node.widgets.find(w => w.name === "image_name");
                    
                    if (!folderWidget || !imageWidget) return;

                    node.updateImages = async (targetImage = null) => {
                        const folder = folderWidget.value;
                        if (!folder) return;
                        try {
                            const resp = await api.fetchApi("/custom_folder/get_images", {
                                method: "POST", body: JSON.stringify({ folder: folder })
                            });
                            const data = await resp.json();
                            const newValues = (data.images && data.images.length > 0) ? data.images : ["No images found"];
                            imageWidget.options.values = newValues;
                            
                            if (targetImage && newValues.includes(targetImage)) {
                                imageWidget.value = targetImage;
                            } else if (!newValues.includes(imageWidget.value)) {
                                imageWidget.value = newValues[0];
                            }
                            node.updatePreview();
                        } catch (e) {
                            console.error("Error fetching images:", e);
                        }
                    };
                    
                    node.updatePreview = async () => {
                        const folder = folderWidget.value;
                        const imageName = imageWidget.value;
                        if (!folder || !imageName || imageName === "No images found" || imageName === "Enter folder path first...") return;
                        
                        try {
                            const resp = await api.fetchApi("/custom_folder/view_preview", {
                                method: "POST",
                                body: JSON.stringify({ folder: folder, image_name: imageName })
                            });
                            const data = await resp.json();
                            if (data.filename) {
                                const img = new Image();
                                img.onload = () => {
                                    node.imgs = [img];
                                    app.graph.setDirtyCanvas(true);
                                };
                                img.src = api.apiURL(`/view?filename=${encodeURIComponent(data.filename)}&type=temp&subfolder=&t=${Date.now()}`);
                            }
                        } catch (e) {
                            console.error("Error updating preview:", e);
                        }
                    };

                    const origFolderCallback = folderWidget.callback;
                    folderWidget.callback = function() {
                        if (origFolderCallback) origFolderCallback.apply(this, arguments);
                        node.updateImages();
                    };
                    
                    const origImageCallback = imageWidget.callback;
                    imageWidget.callback = function() {
                        if (origImageCallback) origImageCallback.apply(this, arguments);
                        node.updatePreview();
                    };

                    node.updateImages();
                }, 150); // تأخير بسيط لضمان تهيئة النود بالكامل
            };
        }
    }
});
"""

js_file = os.path.join(js_dir, "custom_node_ui.js")
with open(js_file, "w", encoding="utf-8") as f:
    f.write(js_code)

WEB_DIRECTORY = "./js"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]