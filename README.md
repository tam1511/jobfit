# JobFit

Chấm và tối ưu CV theo mô tả công việc.

Người dùng tải CV lên và đưa vào một JD — dán trực tiếp hoặc dán link tin tuyển dụng để hệ thống tự lấy nội dung. Kết quả trả về ngay: điểm tổng, breakdown theo từng hạng mục, và các khoảng trống được đánh dấu trực tiếp trên CV của chính người dùng.

Chỉ khi người dùng bấm Tối ưu, một cuộc hội thoại mới mở ra. Cuộc hội thoại đó giới hạn trong đúng những gap vừa tìm được và hỏi từng thiếu sót một.

JobFit không bịa kinh nghiệm. Nó chỉ ra chỗ yếu, hỏi người dùng bổ sung, và diễn đạt lại những gì thực sự có trong CV. Không có template CV trong sản phẩm này — hệ thống làm việc trên đúng tài liệu người dùng đưa vào.

## Tính năng

- Chấm điểm CV theo JD, không cần cấu hình hay hỏi đáp trước
- Lấy nội dung JD từ link tin tuyển dụng
- Điểm tổng dạng vòng tròn, điểm từng hạng mục dạng thanh ngang
- Gap hiển thị inline trên CV theo ba mức màu, không tách thành danh sách riêng
- Hội thoại tối ưu bám theo gap, mỗi lượt một câu hỏi
- Lưu lịch sử theo công ty đã ứng tuyển, so sánh điểm giữa các phiên bản CV
- Tải kết quả về

## Kiến trúc

```
backend/                    FastAPI, venv chuẩn, requirements.txt
frontend/                   Next.js, build tĩnh, FastAPI phục vụ
scripts/                    start/stop cho mac, linux, windows
rubric.json                 Hạng mục chấm điểm, trọng số, tiêu chí đo lường
fixtures/                   Cặp CV-JD mẫu kèm kết quả kỳ vọng
.claude/skills/cv-rubric/   Rubric và quy tắc viết lại CV
```

Toàn bộ đóng gói trong một Docker image. Database là SQLite tạo bên trong container. Ứng dụng trả lời tại `http://localhost:8000`.

## Cài đặt

Tạo file `.env` ở thư mục gốc:

```
OPENROUTER_API_KEY=...
```

Model được chọn phải hỗ trợ function calling và structured outputs. `.env` nằm trong `.gitignore` và không bao giờ được commit.

Khởi động:

```
scripts/start-mac.sh
```

Dừng:

```
scripts/stop-mac.sh
```

Thay `mac` bằng `linux` hoặc dùng `scripts/start-windows.ps1` tùy hệ điều hành.

## Cách chấm điểm

| Hạng mục | Trọng số | Đo bằng |
|---|---:|---|
| Hard Skills Match | 30% | Tỷ lệ kỹ năng bắt buộc trong JD xuất hiện trong CV |
| Experience Match | 25% | Mức độ khớp về số năm và cấp bậc |
| ATS Keywords | 20% | Tỷ lệ cụm từ chuyên ngành của JD xuất hiện trong CV |
| Quantified Achievements | 15% | Tỷ lệ bullet có con số kết quả đo được |
| Formatting & Length | 10% | Cấu trúc, độ dễ đọc, độ dài so với kỳ vọng của JD |

Chấm điểm phải mang tính xác định: cùng một CV và cùng một JD luôn ra cùng một điểm. `fixtures/` tồn tại để chứng minh điều đó — một thay đổi làm vỡ fixtures là một thay đổi hỏng.

Scoring và rewriting là hai lời gọi riêng với hai schema riêng. Thứ gì tính được bằng code thì tính bằng code, không hỏi model.

## Quy trình phát triển

Mỗi đơn vị công việc là một GitHub Issue. Với mỗi issue:

1. Đọc issue qua GitHub tools, không đoán phạm vi
2. Chạy đủ quy trình feature-dev, không bỏ bước nào
3. Viết unit test và integration test, sửa hết những gì test phát hiện
4. Mở Pull Request qua GitHub tools

Issue mơ hồ thì dừng lại và hỏi trước khi viết code.

Toàn bộ know-how chấm điểm và viết lại nằm trong skill `cv-rubric`. Skill là nguồn sự thật duy nhất cho rubric, schema đầu ra và các quy tắc viết lại. Nếu skill chưa bao được một trường hợp thì mở rộng skill, không viết prompt riêng ở chỗ khác.

## Bảo mật và dữ liệu

- JD và CV là input không tin cậy. Chúng đi vào prompt với tư cách dữ liệu, không phải chỉ dẫn.
- Phân quyền là việc của code, quyết định trước khi gọi model. Không bao giờ dùng prompt để thực thi phân quyền.
- CV thường chứa số điện thoại, địa chỉ và thông tin cá nhân. Cân nhắc kỹ trước khi log hoặc lưu.

## Giới hạn

MVP chạy cục bộ. Một tài khoản chủ sở hữu, credentials đọc từ env, tuy schema đã hỗ trợ nhiều người dùng cho sau này. Chưa deploy production.

Công cụ này hỗ trợ diễn đạt lại kinh nghiệm có thật. Nó không đảm bảo kết quả tuyển dụng.

## Tài liệu tham khảo

Công cụ và nền tảng:

- Claude Code — https://code.claude.com
- Agent Skills của Anthropic — https://github.com/anthropics/skills
- Model Context Protocol — https://modelcontextprotocol.io
- GitHub MCP Server — https://github.com/github/github-mcp-server
- Skills marketplace của Vercel — https://skills.sh
- OpenRouter — https://openrouter.ai
- Next.js — https://nextjs.org
- FastAPI — https://fastapi.tiangolo.com

Plugin `feature-dev` và các plugin chính thức khác cài trực tiếp từ trong Claude Code bằng lệnh `/plugin`.

📚 Tham khảo khóa học : [AI Coder](https://www.udemy.com/course/ai-coder-from-vibe-coder-to-agentic-engineer/?couponCode=KEEPLEARNING)

**Lưu ý: Toàn bộ những gì mình chia sẽ đều là những gì mình học và tổng hợp được. No COMMERCIAL intent!!**

## License

MIT
