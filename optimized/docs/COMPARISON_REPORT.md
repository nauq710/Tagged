# BÁO CÁO ĐỐI SÁNH HIỆU NĂNG: BASELINE VS. OPTIMIZED
## Môn học: Mạng Máy Tính (Computer Networks - CO3093)
## Đề tài: Tag, You're Lagged! — Tối ưu hóa Giao thức Tầng Ứng dụng & Đồng bộ Trạng thái Mạng

---

## 1. Tổng quan Kiến trúc

Dự án được triển khai thành hai phiên bản độc lập để phục vụ so sánh và đo đạc thực nghiệm:

| Thành phần | **Bản 1: Baseline** (`/baseline`) | **Bản 2: Optimized** (`/optimized`) |
|:---|:---|:---|
| **Vị trí thư mục** | `D:\Exam\MMT\BTL\baseline` | `D:\Exam\MMT\BTL\optimized` |
| **Giao thức vận chuyển** | WebSocket (`ws://` / `wss://`) | WebSocket (`ws://` / `wss://`) |
| **Cơ chế Snapshot** | Full State Snapshot liên tục (10 Hz) | **Adaptive Delta Snapshot** (10 Hz) |
| **Đàm phán tính năng** | Không (mặc định gửi full state) | **Feature Negotiation** (`join` payload mang cờ `delta: true`) |
| **Cơ chế Fallback** | Không có | Tự động fallback về Full Snapshot nếu delta size > 85% |
| **Tương thích ngược** | Baseline chuẩn | **100% tương thích ngược** với client legacy |
| **Kết quả kiểm thử** | **32/32 tests PASS** | **32/32 tests PASS** |

---

## 2. Thiết kế Giao thức & Kỹ thuật Tối ưu (Delta Snapshot)

### 2.1. Hạn chế của Bản Baseline (Full Snapshot)
- Mỗi chu kỳ 100ms (10 Hz), server tuần tự hóa và broadcast toàn bộ danh sách:
  - Tất cả người chơi (tọa độ `x`, `y`, bán kính, credits, trạng thái tàng hình, sống/chết).
  - Tất cả 32 vật phẩm thu thập (orbs tiers: small, medium, large).
  - Toàn bộ danh sách sự kiện gần nhất (tối đa 32 events).
- Kích thước trung bình mỗi snapshot lên tới **~2.2 KB đến 3.0 KB**.
- Trong kịch bản nhiều người chơi đứng yên hoặc map có ít biến động, việc gửi lặp lại các vật phẩm cố định và người chơi không di chuyển gây lãng phí băng thông mạng nghiêm trọng (**lãng phí ~88%**).

### 2.2. Giải pháp trong Bản Optimized (Adaptive Delta Snapshot)
1. **Theo dõi trạng thái trước đó (Previous State Tracking):**
   - Server lưu `last_snapshots[player_id]` của lần phát sóng trước đó cho từng client.
2. **Lọc trường thay đổi (`encode_delta`):**
   - `phase`, `round`, `winner`: chỉ đính kèm nếu có thay đổi.
   - `players`: chỉ gửi các player có thuộc tính thay đổi (tọa độ, credits, cloak, trạng thái alive). Đính kèm mảng `removed_players` khi có người chơi rời phòng.
   - `items`: chỉ gửi các item được spawn lại khi có người nhặt.
   - `events`: chỉ gửi các event mới sinh ra (dựa theo `event_id > prev_event_id`).
3. **Phục hồi trạng thái phía Client (`applyDelta`):**
   - Client giữ `lastSnapshot` cơ sở. Khi nhận gói tin `type: 'delta'`, client thực hiện patching các thực thể theo `id` và cập nhật giao diện mà không làm mất tính toàn vẹn trạng thái.
4. **Đàm phán tính năng (Protocol Feature Negotiation):**
   - Client hỗ trợ delta gửi `{"type": "join", "delta": true, ...}`.
   - Nếu client không yêu cầu delta (ví dụ các test runner kiểm thử tự động của giảng viên hoặc client cũ), server tự động phục vụ Full Snapshot.

---

## 3. Kết quả Thực nghiệm & Đo lường Tốc độ (Benchmark)

Thực nghiệm đo đạc được thực hiện tự động bằng script [benchmark_comparison.py](../tools/benchmark_comparison.py) với cùng điều kiện môi trường:
- **Số lượng Bot giả lập:** 8 người chơi đồng thời
- **Thời gian chạy:** 8 giây / phiên
- **Cấu hình phòng:** 4 người chơi / phòng (tổng cộng 2 phòng đấu)
- **Tần số gửi input:** 10 Hz (mỗi 100ms gửi 1 lệnh điều khiển ngẫu nhiên)

### Bảng số liệu đối sánh thực tế:

| Tiêu chí đo lường | Baseline (Bản chưa tối ưu) | Optimized (Bản đã tối ưu) | Mức độ chênh lệch / Tiết kiệm |
|:---|:---:|:---:|:---:|
| **Tổng dữ liệu truyền tải (Total Bandwidth)** | **2,033,010 Bytes** (~1.94 MB) | **245,059 Bytes** (~0.23 MB) | **Giảm 87.95% băng thông** 🚀 |
| **Số lượng Full Snapshot** | 648 gói tin | 16 gói tin (chỉ gửi lúc bắt đầu) | Giảm 632 gói full |
| **Số lượng Delta Snapshot** | 0 gói tin | 624 gói tin | Tận dụng 97.5% delta |
| **Kích thước thông điệp trung bình** | **2,190.7 Bytes** | **266.4 Bytes** | **Tiết kiệm 1,924.3 Bytes / tin** |
| **Kích thước thông điệp trung vị (Median)** | **2,947.0 Bytes** | **156.0 Bytes** | **Tiết kiệm 2,791.0 Bytes / tin** |
| **Độ trễ trung vị RTT p50** | 0.70 ms | 0.63 ms | Nhanh hơn 0.07 ms |
| **Độ trễ RTT p95** | 1.69 ms | 1.83 ms | Tương đương (chênh lệch < 0.15ms) |

---

## 4. Đánh giá & Kết luận

1. **Hiệu quả về Băng thông:**
   - Kỹ thuật **Adaptive Delta Snapshot** giúp giảm gần **88%** tổng dung lượng dữ liệu truyền qua WebSocket.
   - Kích thước gói tin snapshot giảm từ gần 3 KB xuống chỉ còn khoảng **156 - 266 Bytes**.
2. **Hiệu năng & Tốc độ Xử lý:**
   - Việc tính toán delta trên Python backend diễn ra cực nhanh bằng từ điển (O(N) với N là số lượng player và item), không làm tăng độ trễ RTT tầng ứng dụng (RTT p50 đạt 0.63 ms).
3. **Tính Đúng đắn và Tuân thủ Luật Chơi:**
   - Tất cả 32 unit tests của giảng viên (`test_engine.py`, `test_browser_simulator.py`, `test_http_ws.py`, `test_outcome.py`, `test_verified_results.py`) đều đạt **100% PASS** trên cả hai phiên bản.
   - Kết quả kết thúc trận đấu (terminal outcome) hoàn toàn trùng khớp với Deterministic Oracle.

---

## 5. Hướng dẫn Chạy Kiểm thử & Tái hiện Kết quả

### Kích hoạt môi trường:
```powershell
d:\Exam\MMT\BTL\.venv\Scripts\activate
```

### Chạy toàn bộ 32 Tests:
```powershell
# Chạy trên bản Baseline:
$base = "d:\Exam\MMT\BTL\baseline"; $env:PYTHONPATH="$base;$base\server"; python -m unittest discover -s "$base\server\tests" -v

# Chạy trên bản Optimized:
$base = "d:\Exam\MMT\BTL\optimized"; $env:PYTHONPATH="$base;$base\server"; python -m unittest discover -s "$base\server\tests" -v
```

### Chạy lại kịch bản Benchmark so sánh tự động:
```powershell
python "d:\Exam\MMT\BTL\optimized\tools\benchmark_comparison.py"
```
