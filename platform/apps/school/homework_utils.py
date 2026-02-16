import os
from werkzeug.utils import secure_filename


def _upload_folder():
    base = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "uploads",
    )
    os.makedirs(base, exist_ok=True)
    return base


def save_homework_files(files, class_id):
    upload_dir = os.path.join(_upload_folder(), f"class_{class_id}")
    os.makedirs(upload_dir, exist_ok=True)
    saved_files = []
    for file in files:
        if file and file.filename:
            filename = secure_filename(file.filename)
            file_path = os.path.join(upload_dir, filename)
            file.save(file_path)
            saved_files.append(filename)
    return saved_files
