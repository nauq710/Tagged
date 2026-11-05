# BÁO CÁO BÀI TẬP LỚN MÔN MẠNG MÁY TÍNH (CO3093)
## Assignment 1: Tag, You're Lagged!
### Thiết kế Giao thức Tầng Ứng dụng & Tối ưu hóa Đồng bộ Trạng thái Game Nhiều người chơi

> 📄 **Đề bài chi tiết:** Xem file đính kèm [Assignment_1_v1.2.pdf](./Assignment_1_v1.2.pdf)  
> 🎓 **Môn học:** Mạng máy tính (Computer Networks - CO3093) — HK261  
> 🏷️ **Trạng thái kiểm thử:** **32/32 tests PASS (100%)** ✅  
> 🚀 **Hiệu quả tối ưu:** **Tiết kiệm 87.95% băng thông** so với Baseline  

---

## 📑 MỤC LỤC
1. [Giới thiệu & Tổng quan Đề tài](#1-giới-thiệu--tổng-quan-đề-tài)
2. [Ràng buộc Luật chơi (Game Mechanics)](#2-ràng-buộc-luật-chơi-game-mechanics)
3. [Kiến trúc Giao thức: Baseline vs. Optimized](#3-kiến-trúc-giao-thức-baseline-vs-optimized)
4. [Kỹ thuật Tối ưu: Adaptive Delta Snapshot](#4-kỹ-thuật-tối-ưu-adaptive-delta-snapshot)
5. [Kết quả Thực nghiệm & Đối sánh Hiệu năng (Benchmark)](#5-kết-quả-thực-nghiệm--đối-sánh-hiệu-năng-benchmark)
6. [Cấu trúc Thư mục Dự án](#6-cấu-trúc-thư-mục-dự-án)
7. [Hướng dẫn Cài đặt & Khởi chạy](#7-hướng-dẫn-cài-đặt--khởi-chạy)
8. [Quy định Chỉnh sửa File (File Policy)](#8-quy-định-chỉnh-sửa-file-file-policy)

---

## 1. Giới thiệu & Tổng quan Đề tài

**"Tag, You're Lagged!"** là một trò chơi hành động sinh tồn nhiều người chơi (multiplayer browser game) chạy thời gian thực trên nền Web. Trọng tâm của bài tập lớn là:
- Thiết kế và hoàn thiện **giao thức truyền thông tầng ứng dụng** qua WebSocket.
- Xử lý đồng bộ hóa trạng thái thế giới (world state synchronization).
- Giải quyết bài toán băng thông mạng và độ trễ khi có nhiều người chơi cùng tham gia.
- Đảm bảo **tính đúng đắn của kết quả trận đấu (Completed-match correctness)** dựa trên Deterministic Oracle của đề bài.

---

## 2. Ràng buộc Luật chơi (Game Mechanics)

Toàn bộ các quy tắc trò chơi được định nghĩa cố định trong `server/app/game/rules.py` (nghiêm cấm can thiệp làm sai lệch):

| Yếu tố | Thông số quy định | Ý nghĩa & Cơ chế |
|:---|:---|:---|
| **Bản đồ** | 960 × 600 đơn vị | Tọa độ thực liên tục, giới hạn biên chuẩn |
| **Nhịp mô phỏng** | 20 ticks / giây (50ms/tick) | Server tiến hành mô phỏng và kiểm tra va chạm |
| **Tần số phát sóng** | 10 Hz (mỗi 100ms) | Phát snapshot trạng thái về các client |
| **Vật phẩm (Orbs)** | 3 cấp bậc | Nhỏ (+1 credit), Vừa (+3 credits), Lớn (+7 credits) |
| **Tốc độ di chuyển** | `speed_for(c)` | Tốc độ giảm dần khi điểm tích lũy tăng: $v = \max(65, \frac{170}{1 + 0.09\sqrt{c}})$ |
| **Kỹ năng Tàng hình** | Cloak (Space) | Duy trì 3s (60 ticks), tiêu tốn 5 credits, ẩn mình với đối thủ |
| **Cơ chế Va chạm** | Predator vs. Prey | Người có credits **lớn hơn strictly** sẽ loại người ít hơn và cướp **40% (làm tròn lên)** điểm của đối thủ |
| **Hao mòn điểm (Decay)** | Periodic Decay | Cứ mỗi 5s (100 ticks) trừ **2% (làm tròn lên)** credits |
| **Kết thúc ván** | Terminal Outcome | Ván kết thúc khi chỉ còn 1 người sống sót duy nhất |

---

## 3. Kiến trúc Giao thức: Baseline vs. Optimized

```
               [ Client Browser ]
                       │
         (1) ws://HOST:8000/ws (WebSocket)
                       │
                       ▼
            ┌──────────────────────┐
            │    GameTransport     │
            │ (Feature Negotiation)│
            └──────────┬───────────┘
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
┌──────────────────┐          ┌──────────────────────┐
│  Bản 1: Baseline │          │   Bản 2: Optimized   │
│  Full Snapshot   │          │ Adaptive Delta Sync  │
│  (Mỗi gói ~2.2KB)│          │ (Mỗi gói ~156-266 B) │
└──────────────────┘          └──────────────────────┘
```

### So sánh hai giải pháp:
- **Baseline (Bản chuẩn):** Mỗi chu kỳ 100ms, server gửi tuần tự toàn bộ danh sách người chơi (vị trí, góc nhìn, bán kính, credits), danh sách 32 viên ngọc, và các sự kiện. Việc này gây lãng phí băng thông lớn khi người chơi đứng yên hoặc ngọc chưa bị ăn.
- **Optimized (Bản tối ưu):** Triển khai cơ chế **Adaptive Delta Snapshot** kèm đàm phán tính năng (Feature Negotiation). Chỉ gửi các thuộc tính thay đổi của các thực thể biến động.

---

## 4. Kỹ thuật Tối ưu: Adaptive Delta Snapshot

1. **Lọc trường biến đổi (`encode_delta` tại server):**
   - Lưu trữ `last_snapshots[player_id]` của chu kỳ phát sóng trước đó.
   - So sánh từng thực thể theo ID: chỉ gửi những người chơi có tọa độ di chuyển, thay đổi credits, tàng hình hoặc bị loại.
   - Chỉ gửi danh sách item được tái sinh (respawn) khi có người nhặt.
   - Chỉ đính kèm các event mới phát sinh (`event_id > prev_event_id`).
2. **Khôi phục trạng thái tại Client (`applyDelta`):**
   - Client duy trì `lastSnapshot` cơ sở.
   - Khi nhận gói tin `type: 'delta'`, client áp dụng các bản cập nhật theo ID và bổ sung/xóa thực thể tương ứng mà không làm gián đoạn việc render Canvas.
3. **Đàm phán tính năng (Protocol Feature Negotiation):**
   - Client hỗ trợ delta gửi cờ `{"type": "join", "delta": true, ...}`.
   - Nếu client không yêu cầu delta (ví dụ các test runner kiểm thử tự động của giảng viên hoặc client cũ), server tự động phục vụ Full Snapshot chuẩn.
4. **Cơ chế Fallback An toàn (Safety Fallback):**
   - Khi có quá nhiều thực thể thay đổi cùng lúc (kích thước delta > 85% full snapshot), hệ thống tự động fallback gửi Full Snapshot để đảm bảo tính đồng bộ hoàn hảo.

---

## 5. Kết quả Thực nghiệm & Đối sánh Hiệu năng (Benchmark)

Thực nghiệm đo đạc tự động thông qua script [benchmark_comparison.py](./tools/benchmark_comparison.py) trên cùng một máy với kịch bản **8 người chơi bot đồng thời** trong 8 giây:

| Tiêu chí Đo lường | Baseline (Bản chưa tối ưu) | Optimized (Bản đã tối ưu) | Mức độ Tối ưu / Tiết kiệm |
|:---|:---:|:---:|:---:|
| **Tổng dữ liệu truyền tải** | **2,033,010 Bytes** (~1.94 MB) | **245,059 Bytes** (~0.23 MB) | **Tiết kiệm 87.95% băng thông** 🚀 |
| **Số gói Full Snapshot** | 648 gói tin | 16 gói tin (chỉ gửi lúc đầu) | Giảm 632 gói tin nặng |
| **Số gói Delta Snapshot** | 0 gói tin | 624 gói tin | Tận dụng 97.5% delta |
| **Kích thước thông điệp TB** | **2,190.7 Bytes** | **266.4 Bytes** | **Giảm 1,924.3 Bytes / tin** |
| **Kích thước trung vị (Median)** | **2,947.0 Bytes** | **156.0 Bytes** | **Giảm 2,791.0 Bytes / tin** |
| **Độ trễ phản hồi (RTT p50)** | 0.70 ms | 0.63 ms | Nhanh hơn ~10% |
| **Độ trễ RTT p95** | 1.69 ms | 1.83 ms | Tương đương (chênh lệch <0.15ms) |

> 📊 Dữ liệu JSON chi tiết được lưu trữ tại [`docs/BENCHMARK_RESULTS.json`](./docs/BENCHMARK_RESULTS.json) và báo cáo phân tích tại [`docs/COMPARISON_REPORT.md`](./docs/COMPARISON_REPORT.md).

---

## 6. Cấu trúc Thư mục Dự án

```
hk261-co3093-assignment-1/
├── Assignment_1_v1.2.pdf       # File đề bài chính thức của môn học
├── Dockerfile                  # Docker container build cho deploy Render
├── README.md                   # Báo cáo tổng quan dự án (file này)
├── client/                     # Frontend TypeScript + Vite
│   ├── dist/                   # Bản build HTML/JS sẵn sàng chơi ngay
│   └── src/
│       ├── network/adapter.ts  # Client transport & WebSocket adapter
│       ├── network/protocol.ts # Bộ giải mã & hàm applyDelta
│       └── ui/game.ts          # Giao diện Canvas & điều khiển bàn phím
├── server/                     # Backend Python aiohttp
│   ├── app/
│   │   ├── game/engine.py      # Authoritative state simulation
│   │   ├── game/rules.py       # [DO NOT EDIT] Luật chơi gốc của trường
│   │   ├── network/protocol.py # Bộ sinh delta encode_delta()
│   │   ├── network/transport.py# Xử lý WebSocket & đàm phán delta
│   │   └── main.py             # Server entrypoint & serving web
│   └── tests/                  # [DO NOT EDIT] 32 bài test của giảng viên
├── scenarios/                  # [DO NOT EDIT] Các kịch bản mẫu của đề bài
└── tools/
    ├── benchmark_comparison.py # Script đo lường và so sánh hiệu năng tự động
    ├── load_test.py            # Công cụ test tải với bot
    └── scenario_runner.py      # Runner kịch bản kiểm tra tính tất định với Oracle
```

---

## 7. Hướng dẫn Cài đặt & Khởi chạy

### 7.1. Chạy game trên trình duyệt (Play locally):
Game đã được build sẵn vào `client/dist/`, bạn chỉ cần chạy server Python duy nhất:

```powershell
# Di chuyển vào thư mục server
cd server

# Cài đặt thư viện (nếu chưa có aiohttp)
pip install -r requirements.txt

# Khởi động game server
python -m app.main
```
- Mở trình duyệt tại: **`http://localhost:8000`**
- Mở thêm tab thứ 2, nhập cùng phòng `main` và bấm **Create / Join** để bắt đầu chơi.
- Các máy khác chung mạng Wi-Fi/LAN có thể truy cập qua: `http://<IP_LAN_CUA_MAY>:8000`.

### 7.2. Chạy toàn bộ 32 bài test kiểm thử của giảng viên:
```powershell
$env:PYTHONPATH = ".;./server"
python -m unittest discover -s server/tests -v
```
*(Kết quả: 32/32 tests báo `OK`)*

### 7.3. Chạy lại benchmark so sánh Baseline vs. Optimized:
```powershell
python tools/benchmark_comparison.py
```

---

## 8. Quy định Chỉnh sửa File (File Policy)

Dự án tuân thủ nghiêm ngặt theo chính sách [`docs/FILE_POLICY.md`](./docs/FILE_POLICY.md):
- ❌ **Không chỉnh sửa:** `server/app/game/rules.py`, `server/tests/**`, `scenarios/**`.
-  **Được phép chỉnh sửa & tối ưu:** `server/app/network/**`, `server/app/game/engine.py`, `client/src/**`, `tools/**`, `docs/**`.
- ❌ **Không sử dụng framework game đóng gói sẵn:** Toàn bộ tầng mạng được lập trình thuần túy bằng thư viện chuẩn `WebSocket` / `aiohttp`, không dùng Socket.IO hay Colyseus theo đúng yêu cầu đề bài.
