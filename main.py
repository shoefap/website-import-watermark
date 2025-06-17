import os
import time
import threading
import traceback
import uuid
from flask import Flask, request, render_template, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from moviepy.editor import VideoFileClip, TextClip, ImageClip, CompositeVideoClip
from PIL import Image
import numpy as np
from proglog import ProgressBarLogger

# --- Cấu hình ---
UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'processed'
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg'}
MAX_CONTENT_LENGTH = 50 * 1024 * 1024

app = Flask(__name__)
app.config.update({
    'UPLOAD_FOLDER': UPLOAD_FOLDER,
    'PROCESSED_FOLDER': PROCESSED_FOLDER,
    'MAX_CONTENT_LENGTH': MAX_CONTENT_LENGTH,
    'SECRET_KEY': 'supersecretkey_for_flash'
})

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

tasks = {}

# --- Lớp và hàm hỗ trợ ---

class MyLogger(ProgressBarLogger):
    def __init__(self, task_id):
        super().__init__()
        self.task_id = task_id

    def bars_callback(self, bar, attr, value, old_value=None):
        total = self.bars[bar]['total']
        if total > 0 and self.task_id in tasks:
            tasks[self.task_id]['progress'] = int((value / total) * 100)

def process_video_task(task_id, video_path, output_path, options):
    """Hàm xử lý video chạy trong luồng nền."""
    try:
        tasks[task_id]['status'] = 'processing'
        logger = MyLogger(task_id)

        video = VideoFileClip(video_path)
        watermark_clip = None

        # Tạo watermark clip dựa trên tùy chọn
        if options.get('image_path'):
            with Image.open(options['image_path']) as img:
                img = img.convert("RGBA")
                target_width = video.w * (options['size_percent'] / 100.0)
                w_percent = target_width / float(img.size[0])
                h_size = int(float(img.size[1]) * w_percent)
                img_resized = img.resize((int(target_width), h_size), Image.Resampling.LANCZOS)
                watermark_array = np.array(img_resized)
                watermark_clip = ImageClip(watermark_array)
        elif options.get('text_content'):
            watermark_clip = TextClip(
                options['text_content'],
                fontsize=options['font_size'],
                color=options['font_color'],
                stroke_color='black',
                stroke_width=1.5
            )

        if not watermark_clip:
            raise ValueError("Không thể tạo watermark clip.")

        # Áp dụng các hiệu ứng và vị trí
        watermark_clip = watermark_clip.set_duration(video.duration).set_opacity(options['opacity'])

        # Tính toán vị trí bằng pixel từ phần trăm
        # pos_x/y_percent là vị trí tâm của watermark
        watermark_w, watermark_h = watermark_clip.size
        x_pos = (video.w * (options['pos_x_percent'] / 100.0)) - (watermark_w / 2)
        y_pos = (video.h * (options['pos_y_percent'] / 100.0)) - (watermark_h / 2)

        watermark_clip = watermark_clip.set_pos((x_pos, y_pos))

        # Kết hợp và ghi file
        result = CompositeVideoClip([video, watermark_clip])
        result.write_videofile(
            output_path, codec='libx264', audio_codec='aac',
            temp_audiofile=f'temp-audio-{task_id}.m4a', remove_temp=True, logger=logger
        )

        video.close()
        watermark_clip.close()

        tasks[task_id].update({
            'status': 'complete',
            'progress': 100,
            'filename': os.path.basename(output_path)
        })
    except Exception as e:
        print(f"--- Lỗi chi tiết trong task {task_id} ---\n{traceback.format_exc()}\n---------------------------------------")
        if task_id in tasks:
            tasks[task_id].update({'status': 'error', 'error': str(e)})
    finally:
        if os.path.exists(video_path): os.remove(video_path)
        if options.get('image_path') and os.path.exists(options['image_path']):
            os.remove(options['image_path'])


def periodic_cleanup(interval=1800, max_age=3600):
    """Dọn dẹp các file đã xử lý cũ hơn 1 giờ, chạy mỗi 30 phút."""
    print("Luồng dọn dẹp định kỳ đã được bắt đầu.")
    while True:
        time.sleep(interval)
        now = time.time()
        try:
            for filename in os.listdir(PROCESSED_FOLDER):
                file_path = os.path.join(PROCESSED_FOLDER, filename)
                if os.path.isfile(file_path) and (now - os.path.getmtime(file_path)) > max_age:
                    os.remove(file_path)
                    print(f"Đã dọn dẹp tệp cũ: {file_path}")
        except Exception as e:
            print(f"Lỗi khi dọn dẹp: {e}")

# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_video_request():
    try:
        if 'video' not in request.files or request.files['video'].filename == '':
            return jsonify({'error': 'Chưa chọn tệp video.'}), 400
        video_file = request.files['video']
        if not allowed_file(video_file.filename, ALLOWED_VIDEO_EXTENSIONS):
            return jsonify({'error': 'Định dạng video không được hỗ trợ.'}), 400

        options = {
            'text_content': request.form.get('watermark_text'),
            'font_size': int(request.form.get('font_size', 35)),
            'font_color': request.form.get('font_color', '#FFFFFF'),
            'size_percent': float(request.form.get('size_percent', 15)),
            'opacity': float(request.form.get('opacity', 1.0)),
            'pos_x_percent': float(request.form.get('pos_x', 85)),
            'pos_y_percent': float(request.form.get('pos_y', 85)),
            'image_path': None
        }

        image_file = request.files.get('watermark_image')
        has_image = image_file and image_file.filename != ''
        if has_image:
            if not allowed_file(image_file.filename, ALLOWED_IMAGE_EXTENSIONS):
                return jsonify({'error': 'Định dạng ảnh không được hỗ trợ.'}), 400
        elif not options['text_content'].strip():
             return jsonify({'error': 'Vui lòng cung cấp watermark.'}), 400

        task_id = str(uuid.uuid4())
        video_fn = f"{task_id}_{secure_filename(video_file.filename)}"
        video_path = os.path.join(UPLOAD_FOLDER, video_fn)
        video_file.save(video_path)

        if has_image:
            image_fn = f"wm_{task_id}_{secure_filename(image_file.filename)}"
            options['image_path'] = os.path.join(UPLOAD_FOLDER, image_fn)
            image_file.save(options['image_path'])

        output_fn = f"watermarked_{video_fn}"
        output_path = os.path.join(PROCESSED_FOLDER, output_fn)

        tasks[task_id] = {'status': 'starting', 'progress': 0}

        thread = threading.Thread(target=process_video_task, args=(task_id, video_path, output_path, options))
        thread.daemon = True
        thread.start()

        return jsonify({'task_id': task_id})
    except Exception as e:
        return jsonify({'error': f'Lỗi máy chủ: {e}'}), 500


@app.route('/status/<task_id>')
def task_status(task_id):
    return jsonify(tasks.get(task_id, {}))

@app.route('/download/<task_id>')
def download_file(task_id):
    task = tasks.get(task_id, {})
    if task.get('status') == 'complete':
        return send_from_directory(PROCESSED_FOLDER, task.get('filename'), as_attachment=True)
    return "Tệp không sẵn sàng hoặc đã xảy ra lỗi.", 404

def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

if __name__ == '__main__':
    cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
    cleanup_thread.start()
    app.run(host='0.0.0.0', port=8080)
