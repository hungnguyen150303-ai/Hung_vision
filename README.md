# Chạy trong thư mục Vision/
git clone https://github.com/hungnguyen150303-ai/Hung_vision.git
shopt -s dotglob nullglob
mv -n Hung_vision/* ./        # -n: không ghi đè (dùng -i để hỏi, bỏ đi để ghi đè im lặng)
shopt -u dotglob
rmdir Hung_vision 2>/dev/null || true
