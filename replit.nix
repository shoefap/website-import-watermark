# File: replit.nix
# Mô tả: File này cấu hình môi trường hệ thống của Replit.
# Chúng ta thêm `pkgs.ffmpeg` để thư viện moviepy có thể hoạt động.

{ pkgs }: {
  deps = [
    pkgs.python310Full
    # DÒNG ĐÃ SỬA: `pkgs.replitPackages.poetry` đã được thay thế bằng `pkgs.poetry`
    pkgs.poetry
    pkgs.ffmpeg
  ];

  env = {
    PYTHON_LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
      # Thêm các thư viện cần thiết ở đây nếu có
    ];
    PYTHONBIN = "${pkgs.python310Full}/bin/python3.10";
    LANG = "en_US.UTF-8";
  };
}
