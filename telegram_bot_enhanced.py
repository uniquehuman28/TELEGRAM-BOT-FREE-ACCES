import os
import re
import uuid
import asyncio
import shutil
from pathlib import Path
from typing import List, Tuple
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, InputMediaDocument, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== KONFIGURASI ====================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMIN_IDS = [7818451398]
QRIS_PATH = "/path/to/qris.jpg"  # Path ke file QRIS di VPS
BANK_INFO = """
💳 **Informasi Rekening:**
BCA: 1234567890 a.n. Nama Pemilik
BNI: 0987654321 a.n. Nama Pemilik
DANA: 081234567890
OVO: 081234567890
"""
DONASI_INFO = """
🙏 **Terima kasih atas niat baik Anda!**

Donasi akan digunakan untuk:
• Maintenance server VPS
• Pengembangan fitur baru
• Upgrade infrastruktur bot

Setiap donasi sangat berarti! 💚
"""

# ==================== SETUP ====================
BASE_DIR = Path(__file__).parent.resolve()
SESSIONS_DIR = BASE_DIR / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

def format_number(raw: str, default_cc="+62", min_len=8, max_len=15):
    """Fungsi format nomor telepon - TIDAK DIUBAH dari versi asli"""
    raw = (raw or "").strip()
    m = re.search(r"\+?\d{3,}", raw)
    if not m:
        return None
    token = m.group(0)

    if token.startswith("00"):
        token = "+" + token[2:]
    elif token.startswith("0"):
        token = default_cc + token[1:]
    elif not token.startswith("+"):
        token = "+" + token

    digits = re.sub(r"\D", "", token)
    if not (min_len <= len(digits) <= max_len):
        return None

    patterns = {
        "+62": r"(\+62)(\d{3,4})(\d+)",
        "+852": r"(\+852)(\d{4})(\d{4})",
        "+60": r"(\+60)(\d{2,3})(\d+)",
        "+65": r"(\+65)(\d{4})(\d{4})",
        "+91": r"(\+91)(\d{5})(\d{5})",
        "+92": r"(\+92)(\d{3,4})(\d+)",
        "+880": r"(\+880)(\d{3,4})(\d+)",
        "+966": r"(\+966)(\d{3})(\d+)",
        "+971": r"(\+971)(\d{2,3})(\d+)",
        "+63": r"(\+63)(\d{3})(\d+)",
        "+234": r"(\+234)(\d{3})(\d+)",
        "+1": r"(\+1)(\d{3})(\d{3})(\d{4})",
    }
    for code, pattern in patterns.items():
        if token.startswith(code):
            m2 = re.match(pattern, token)
            if m2:
                return " ".join(m2.groups())
            break
    return token

def remove_duplicates(numbers: List[str]) -> List[str]:
    seen, result = set(), []
    for num in numbers:
        if num not in seen:
            seen.add(num)
            result.append(num)
    return result

def list_txt_files(folder_path: Path) -> List[Path]:
    return sorted(Path(folder_path).glob("*.txt"))

def list_vcf_files(folder_path: Path) -> List[Path]:
    return sorted(Path(folder_path).glob("*.vcf"))

def write_vcard_batch(vcf_path: Path, contact_fullname_number_pairs: List[Tuple[str, str]]):
    temp_path = str(vcf_path) + ".tmp"
    with open(temp_path, "w", encoding="utf-8", newline="") as vcf:
        for fullname, num in contact_fullname_number_pairs:
            vcf.write("BEGIN:VCARD\r\n")
            vcf.write("VERSION:3.0\r\n")
            vcf.write(f"FN:{fullname}\r\n")
            parts = fullname.split(" ", 1)
            family = parts[1] if len(parts) > 1 else ""
            given = parts[0]
            vcf.write(f"N:{family};{given};;;\r\n")
            vcf.write(f"UID:{uuid.uuid4()}\r\n")
            vcf.write(f"TEL;TYPE=CELL:{num}\r\n")
            vcf.write("END:VCARD\r\n\r\n")
    os.replace(temp_path, vcf_path)

def parse_vcf_numbers(vcf_path: Path) -> List[str]:
    """Parse file VCF dan ekstrak nomor telepon"""
    numbers = []
    try:
        with open(vcf_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        # Regex untuk mencari nomor telepon di VCF
        tel_patterns = [
            r"TEL[^:]*:([^\r\n]+)",
            r"PHONE[^:]*:([^\r\n]+)",
        ]
        
        for pattern in tel_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                # Bersihkan nomor dari karakter yang tidak perlu
                clean_number = re.sub(r"[^\d+\-\s()]", "", match.strip())
                formatted = format_number(clean_number)
                if formatted:
                    numbers.append(formatted)
    except Exception as e:
        print(f"Error parsing {vcf_path}: {e}")
    
    return numbers

def get_disk_usage():
    """Mendapatkan informasi penggunaan disk VPS"""
    total, used, free = shutil.disk_usage("/")
    
    total_gb = total / (1024**3)
    used_gb = used / (1024**3)
    free_gb = free / (1024**3)
    
    usage_percent = (used / total) * 100
    
    # Progress bar
    bar_length = 10
    filled_length = int(bar_length * usage_percent // 100)
    bar = "█" * filled_length + "░" * (bar_length - filled_length)
    
    return {
        "total_gb": total_gb,
        "used_gb": used_gb,
        "free_gb": free_gb,
        "usage_percent": usage_percent,
        "progress_bar": bar
    }

def plan_outputs(src_folder: Path, base_file_name: str, per_file: int, output_dir: Path):
    plan = []
    conflicts = set()
    batch_idx_global = 0

    txt_files = list_txt_files(src_folder)
    if not txt_files:
        raise ValueError("Folder tidak berisi file .txt.")

    all_numbers = []
    invalid_count = 0
    for src in txt_files:
        with open(src, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                n = format_number(line)
                if n:
                    all_numbers.append(n)
                else:
                    invalid_count += 1

    all_numbers = remove_duplicates(all_numbers)
    total_contacts = len(all_numbers)
    if total_contacts == 0:
        return [], 0, conflicts, invalid_count

    for idx in range(0, len(all_numbers), per_file):
        batch_idx_global += 1
        target_name = f"{base_file_name} {batch_idx_global}.vcf"
        target_path = output_dir / target_name
        if target_path.exists():
            conflicts.add(str(target_path))
        plan.append((all_numbers[idx:idx+per_file], target_path))

    return plan, total_contacts, conflicts, invalid_count

def plan_vcf_to_txt(src_folder: Path, output_dir: Path):
    """Plan untuk konversi VCF ke TXT"""
    vcf_files = list_vcf_files(src_folder)
    if not vcf_files:
        raise ValueError("Folder tidak berisi file .vcf.")

    all_numbers = []
    invalid_count = 0
    
    for vcf_file in vcf_files:
        numbers = parse_vcf_numbers(vcf_file)
        all_numbers.extend(numbers)
    
    # Remove duplicates
    all_numbers = remove_duplicates(all_numbers)
    total_numbers = len(all_numbers)
    
    if total_numbers == 0:
        return None, 0, invalid_count
    
    # Output ke satu file TXT
    output_path = output_dir / "extracted_numbers.txt"
    return all_numbers, total_numbers, output_path

class UploadStates(StatesGroup):
    # TXT to VCF states
    collecting_txt = State()
    ask_contact = State()
    ask_outbase = State()
    ask_perfile = State()
    processing_txt = State()
    
    # VCF to TXT states
    collecting_vcf = State()
    processing_vcf = State()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

def session_paths(user_id: int) -> Tuple[Path, Path]:
    in_dir = SESSIONS_DIR / str(user_id) / "in"
    out_dir = SESSIONS_DIR / str(user_id) / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    return in_dir, out_dir

def clear_session(user_id: int):
    user_dir = SESSIONS_DIR / str(user_id)
    if user_dir.exists():
        shutil.rmtree(user_dir, ignore_errors=True)

def create_main_menu(is_admin=False):
    """Membuat menu utama inline keyboard"""
    keyboard = [
        [InlineKeyboardButton(text="📄 TXT→VCF", callback_data="txt_to_vcf")],
        [InlineKeyboardButton(text="📇 VCF→TXT", callback_data="vcf_to_txt")],
        [InlineKeyboardButton(text="ℹ️ Cara Penggunaan", callback_data="help")],
        [InlineKeyboardButton(text="💰 Donasi", callback_data="donasi")]
    ]
    
    if is_admin:
        keyboard.append([InlineKeyboardButton(text="🖥️ Info VPS", callback_data="vpsinfo")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def create_donasi_keyboard():
    """Keyboard untuk fitur donasi"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Saya Sudah Donasi", callback_data="sudah_donasi")]
    ])

@dp.message(Command("start"))
async def start_cmd(msg: Message, state: FSMContext):
    clear_session(msg.from_user.id)
    session_paths(msg.from_user.id)
    await state.clear()
    
    is_admin = msg.from_user.id in ADMIN_IDS
    welcome_text = f"""
🤖 **Selamat datang di Bot Konversi Kontak!**

Halo {msg.from_user.first_name}! 👋

Pilih fitur yang ingin kamu gunakan:

📄 **TXT→VCF**: Konversi file teks menjadi kontak vCard
📇 **VCF→TXT**: Ekstrak nomor telepon dari kontak vCard
ℹ️ **Cara Penggunaan**: Panduan lengkap penggunaan bot
💰 **Donasi**: Dukung pengembangan bot ini
"""
    
    if is_admin:
        welcome_text += "\n🖥️ **Info VPS**: Lihat status server (Admin)"
    
    await msg.answer(welcome_text, reply_markup=create_main_menu(is_admin))

@dp.callback_query(F.data == "txt_to_vcf")
async def callback_txt_to_vcf(call: CallbackQuery, state: FSMContext):
    await call.answer()
    clear_session(call.from_user.id)
    session_paths(call.from_user.id)
    await state.set_state(UploadStates.collecting_txt)
    await state.update_data(uploaded_files=[])
    
    await call.message.edit_text(
        "📄 **Mode: TXT → VCF**\n\n"
        "Kirimkan satu atau beberapa file .txt yang berisi nomor telepon (satu nomor per baris).\n\n"
        "Jika sudah selesai mengupload, ketik /konfirmasi"
    )

@dp.callback_query(F.data == "vcf_to_txt")
async def callback_vcf_to_txt(call: CallbackQuery, state: FSMContext):
    await call.answer()
    clear_session(call.from_user.id)
    session_paths(call.from_user.id)
    await state.set_state(UploadStates.collecting_vcf)
    await state.update_data(uploaded_files=[])
    
    await call.message.edit_text(
        "📇 **Mode: VCF → TXT**\n\n"
        "Kirimkan satu atau beberapa file .vcf (kontak vCard).\n\n"
        "Jika sudah selesai mengupload, ketik /proses"
    )

@dp.callback_query(F.data == "help")
async def callback_help(call: CallbackQuery):
    await call.answer()
    help_text = """
📋 **CARA PENGGUNAAN BOT**

🔹 **TXT → VCF (Teks ke Kontak)**
1️⃣ Pilih "📄 TXT→VCF" dari menu utama
2️⃣ Upload file .txt berisi nomor telepon (satu nomor per baris)
3️⃣ Ketik /konfirmasi setelah selesai upload
4️⃣ Masukkan nama kontak dasar (contoh: "Customer")
5️⃣ Masukkan nama file output (contoh: "HKSIANG")
6️⃣ Tentukan jumlah kontak per file VCF (contoh: 50)
7️⃣ Bot akan memproses dan mengirim file VCF

🔹 **VCF → TXT (Kontak ke Teks)**
1️⃣ Pilih "📇 VCF→TXT" dari menu utama
2️⃣ Upload file .vcf (kontak vCard)
3️⃣ Ketik /proses setelah selesai upload
4️⃣ Bot akan mengekstrak nomor telepon ke file .txt

📝 **Format Nomor yang Didukung:**
• Indonesia: +62, 08xx
• Malaysia: +60
• Singapura: +65
• Hong Kong: +852
• India: +91
• Dan negara lainnya...

💡 **Tips:**
• File akan otomatis dihapus setelah proses selesai
• Nomor duplikat akan dihilangkan otomatis
• Format nomor akan diseragamkan

❓ **Butuh bantuan?** Hubungi admin!
    """
    
    back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Kembali ke Menu", callback_data="back_to_menu")]
    ])
    
    await call.message.edit_text(help_text, reply_markup=back_keyboard)

@dp.callback_query(F.data == "donasi")
async def callback_donasi(call: CallbackQuery):
    await call.answer()
    
    try:
        # Coba kirim foto QRIS jika file ada
        if Path(QRIS_PATH).exists():
            photo = FSInputFile(QRIS_PATH)
            caption_text = f"""
💰 **DONASI UNTUK BOT**

{DONASI_INFO}

{BANK_INFO}

Atau scan QRIS di atas! 📱

Terima kasih atas dukungan Anda! 🙏❤️
            """
            
            await call.message.answer_photo(
                photo=photo,
                caption=caption_text,
                reply_markup=create_donasi_keyboard()
            )
        else:
            # Jika file QRIS tidak ada, kirim teks saja
            donate_text = f"""
💰 **DONASI UNTUK BOT**

{DONASI_INFO}

{BANK_INFO}

Terima kasih atas dukungan Anda! 🙏❤️
            """
            await call.message.edit_text(donate_text, reply_markup=create_donasi_keyboard())
            
    except Exception as e:
        await call.message.edit_text(
            f"💰 **DONASI UNTUK BOT**\n\n{DONASI_INFO}\n\n{BANK_INFO}\n\nTerima kasih atas dukungan Anda! 🙏❤️",
            reply_markup=create_donasi_keyboard()
        )

@dp.callback_query(F.data == "sudah_donasi")
async def callback_sudah_donasi(call: CallbackQuery):
    await call.answer("Terima kasih atas donasi Anda! ❤️")
    
    user = call.from_user
    username = f"@{user.username}" if user.username else user.full_name
    now = datetime.now().strftime("%d-%m-%Y %H:%M")
    
    # Kirim ucapan terima kasih ke user
    await call.message.edit_text(
        "🙏 **Terima kasih atas donasi Anda!**\n\n"
        "Setiap donasi sangat berarti untuk pengembangan bot ini.\n"
        "Semoga bot ini terus bermanfaat! ❤️\n\n"
        "Klik /start untuk kembali menggunakan bot."
    )
    
    # Kirim notifikasi ke semua admin
    notification_text = f"""
💌 **Donasi Baru Masuk!**

👤 **Dari:** {username}
🕐 **Waktu:** {now}
🆔 **User ID:** `{user.id}`

Seseorang telah menekan tombol "Saya Sudah Donasi"! 🎉
    """
    
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, notification_text)
        except:
            pass  # Abaikan error jika admin tidak bisa dihubungi

@dp.callback_query(F.data == "vpsinfo")
async def callback_vpsinfo(call: CallbackQuery):
    await call.answer()
    
    if call.from_user.id not in ADMIN_IDS:
        await call.message.edit_text("❌ Anda tidak memiliki akses ke fitur ini.")
        return
    
    try:
        disk_info = get_disk_usage()
        
        info_text = f"""
🖥️ **INFORMASI VPS**

💾 **Disk Usage:**
📊 {disk_info['progress_bar']} {disk_info['usage_percent']:.1f}%

📈 **Total:** {disk_info['total_gb']:.1f} GB
📊 **Terpakai:** {disk_info['used_gb']:.1f} GB  
📉 **Tersisa:** {disk_info['free_gb']:.1f} GB

⏰ **Waktu Check:** {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}
        """
        
        back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Kembali ke Menu", callback_data="back_to_menu")]
        ])
        
        await call.message.edit_text(info_text, reply_markup=back_keyboard)
        
    except Exception as e:
        await call.message.edit_text(f"❌ Error mengambil info VPS: {e}")

@dp.callback_query(F.data == "back_to_menu")
async def callback_back_to_menu(call: CallbackQuery):
    await call.answer()
    is_admin = call.from_user.id in ADMIN_IDS
    
    welcome_text = f"""
🤖 **Selamat datang di Bot Konversi Kontak!**

Halo {call.from_user.first_name}! 👋

Pilih fitur yang ingin kamu gunakan:

📄 **TXT→VCF**: Konversi file teks menjadi kontak vCard
📇 **VCF→TXT**: Ekstrak nomor telepon dari kontak vCard
ℹ️ **Cara Penggunaan**: Panduan lengkap penggunaan bot
💰 **Donasi**: Dukung pengembangan bot ini
"""
    
    if is_admin:
        welcome_text += "\n🖥️ **Info VPS**: Lihat status server (Admin)"
    
    await call.message.edit_text(welcome_text, reply_markup=create_main_menu(is_admin))

# ==================== HANDLERS UNTUK TXT TO VCF ====================

@dp.message(UploadStates.collecting_txt, F.document)
async def handle_txt_document(msg: Message, state: FSMContext):
    doc = msg.document
    if not (doc.file_name.lower().endswith(".txt") or doc.mime_type == "text/plain"):
        await msg.reply("❌ Hanya mendukung file .txt.")
        return

    in_dir, _ = session_paths(msg.from_user.id)
    dest = in_dir / doc.file_name

    file = await bot.get_file(doc.file_id)
    await bot.download_file(file.file_path, destination=dest)

    data = await state.get_data()
    uploaded = data.get("uploaded_files", [])
    uploaded.append(doc.file_name)
    await state.update_data(uploaded_files=uploaded)

    await msg.reply(
        f"✅ {doc.file_name} tersimpan. Total: {len(uploaded)} file.\n"
        f"Ketik /konfirmasi jika sudah selesai."
    )

@dp.message(Command("konfirmasi"))
async def cmd_konfirmasi(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != UploadStates.collecting_txt.state:
        await msg.reply("❌ Command ini hanya bisa digunakan saat mode TXT→VCF.")
        return
        
    data = await state.get_data()
    uploaded = data.get("uploaded_files", [])
    if not uploaded:
        await msg.reply("Belum ada file .txt yang diunggah. Unggah dulu lalu ketik /konfirmasi.")
        return

    summary = "\n".join([f"• {name}" for name in uploaded])
    await msg.reply(
        f"📂 File yang diunggah ({len(uploaded)}):\n{summary}\n\n"
        f"Sekarang masukkan Nama Kontak Dasar:"
    )
    await state.set_state(UploadStates.ask_contact)

@dp.message(UploadStates.ask_contact)
async def ask_outbase(msg: Message, state: FSMContext):
    contact = (msg.text or "").strip()
    if not contact:
        await msg.reply("Nama kontak tidak boleh kosong. Coba lagi:")
        return
    await state.update_data(contact_name=contact)
    await state.set_state(UploadStates.ask_outbase)
    await msg.reply("Masukkan Nama File Output Dasar (CONTOH : HKSIANG):")

@dp.message(UploadStates.ask_outbase)
async def ask_perfile(msg: Message, state: FSMContext):
    outbase = (msg.text or "").strip()
    if not outbase:
        await msg.reply("Nama file dasar tidak boleh kosong. Coba lagi:")
        return
    await state.update_data(base_file=outbase)
    await state.set_state(UploadStates.ask_perfile)
    await msg.reply("Berapa kontak maksimal per file .vcf? (angka, Contoh : 50)")

@dp.message(UploadStates.ask_perfile)
async def process_txt_inputs(msg: Message, state: FSMContext):
    try:
        per_file = int((msg.text or "").strip())
        if per_file <= 0:
            raise ValueError
    except ValueError:
        await msg.reply("Harus berupa angka > 0. Coba lagi:")
        return

    data = await state.get_data()
    contact_name = data["contact_name"]
    base_file_name = data["base_file"]

    in_dir, out_dir = session_paths(msg.from_user.id)
    await state.set_state(UploadStates.processing_txt)
    status = await msg.reply("⏳ Memproses... Donasi ke QRIS di pp bot ini untuk proses yang lebih cepat😅")

    try:
        plan, total_contacts, conflicts, invalid_count = plan_outputs(
            src_folder=in_dir,
            base_file_name=base_file_name,
            per_file=per_file,
            output_dir=out_dir
        )

        if total_contacts == 0:
            await status.edit_text("Tidak ada nomor valid di file yang diunggah.")
            clear_session(msg.from_user.id)
            await state.clear()
            return

        contact_counter = 1
        for batch, target_path in plan:
            pairs = []
            for num in batch:
                fullname = f"{contact_name} {contact_counter}"
                pairs.append((fullname, num))
                contact_counter += 1
            write_vcard_batch(target_path, pairs)

        vcf_files = list(out_dir.glob("*.vcf"))
        
        def get_file_number(filepath):
            name = filepath.stem
            parts = name.split()
            try:
                return int(parts[-1])
            except:
                return 0
                
        vcf_files_sorted = sorted(vcf_files, key=get_file_number)
        
        summary = (
            f"✅ Selesai!\n"
            f"• Total kontak valid: {total_contacts}\n"
            f"• Baris di-skip (invalid): {invalid_count}\n"
            f"• File VCF: {len(vcf_files_sorted)}"
        )
        await status.edit_text(summary)
        
        if len(vcf_files_sorted) == 1:
            file_input = FSInputFile(vcf_files_sorted[0])
            await msg.answer_document(document=file_input)
        else:
            for i in range(0, len(vcf_files_sorted), 10):
                batch = vcf_files_sorted[i:i+10]
                media = []
                for fp in batch:
                    media.append(InputMediaDocument(media=FSInputFile(fp)))
                await msg.answer_media_group(media=media)

        # Auto hapus cache setelah selesai
        clear_session(msg.from_user.id)
        await state.clear()
        
        # Kirim menu utama lagi
        is_admin = msg.from_user.id in ADMIN_IDS
        await msg.answer("✨ Proses selesai! Cache telah dibersihkan.\n\nSilakan pilih fitur lain:", 
                        reply_markup=create_main_menu(is_admin))

    except Exception as e:
        await status.edit_text(f"❌ Terjadi error: {e}")
        clear_session(msg.from_user.id)
        await state.clear()

# ==================== HANDLERS UNTUK VCF TO TXT ====================

@dp.message(UploadStates.collecting_vcf, F.document)
async def handle_vcf_document(msg: Message, state: FSMContext):
    doc = msg.document
    if not (doc.file_name.lower().endswith(".vcf") or doc.mime_type in ["text/vcard", "text/x-vcard"]):
        await msg.reply("❌ Hanya mendukung file .vcf (vCard).")
        return

    in_dir, _ = session_paths(msg.from_user.id)
    dest = in_dir / doc.file_name

    file = await bot.get_file(doc.file_id)
    await bot.download_file(file.file_path, destination=dest)

    data = await state.get_data()
    uploaded = data.get("uploaded_files", [])
    uploaded.append(doc.file_name)
    await state.update_data(uploaded_files=uploaded)

    await msg.reply(
        f"✅ {doc.file_name} tersimpan. Total: {len(uploaded)} file.\n"
        f"Ketik /proses jika sudah selesai."
    )

@dp.message(Command("proses"))
async def cmd_proses_vcf(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != UploadStates.collecting_vcf.state:
        await msg.reply("❌ Command ini hanya bisa digunakan saat mode VCF→TXT.")
        return
        
    data = await state.get_data()
    uploaded = data.get("uploaded_files", [])
    if not uploaded:
        await msg.reply("Belum ada file .vcf yang diunggah. Unggah dulu lalu ketik /proses.")
        return

    summary = "\n".join([f"• {name}" for name in uploaded])
    status = await msg.reply(
        f"📂 File yang akan diproses ({len(uploaded)}):\n{summary}\n\n"
        f"⏳ Sedang memproses..."
    )

    await state.set_state(UploadStates.processing_vcf)
    
    try:
        in_dir, out_dir = session_paths(msg.from_user.id)
        
        # Parse semua file VCF
        all_numbers = []
        processed_files = 0
        
        vcf_files = list_vcf_files(in_dir)
        for vcf_file in vcf_files:
            numbers = parse_vcf_numbers(vcf_file)
            all_numbers.extend(numbers)
            processed_files += 1
        
        # Remove duplicates
        all_numbers = remove_duplicates(all_numbers)
        total_numbers = len(all_numbers)
        
        if total_numbers == 0:
            await status.edit_text("❌ Tidak ada nomor telepon valid yang ditemukan dalam file VCF.")
            clear_session(msg.from_user.id)
            await state.clear()
            return
        
        # Tulis ke file TXT
        output_path = out_dir / "extracted_numbers.txt"
        with open(output_path, "w", encoding="utf-8") as f:
            for number in all_numbers:
                f.write(f"{number}\n")
        
        # Kirim hasil
        summary_text = (
            f"✅ **Ekstraksi Selesai!**\n\n"
            f"📊 **Statistik:**\n"
            f"• File VCF diproses: {processed_files}\n"
            f"• Total nomor diekstrak: {total_numbers}\n"
            f"• Duplikat dihapus: otomatis\n\n"
            f"📁 File hasil berisi nomor telepon (1 per baris)"
        )
        
        await status.edit_text(summary_text)
        
        # Kirim file hasil
        file_input = FSInputFile(output_path)
        await msg.answer_document(
            document=file_input,
            caption="📄 File berisi nomor telepon yang diekstrak dari VCF"
        )
        
        # Auto hapus cache setelah selesai
        clear_session(msg.from_user.id)
        await state.clear()
        
        # Kirim menu utama lagi
        is_admin = msg.from_user.id in ADMIN_IDS
        await msg.answer("✨ Proses selesai! Cache telah dibersihkan.\n\nSilakan pilih fitur lain:", 
                        reply_markup=create_main_menu(is_admin))
        
    except Exception as e:
        await status.edit_text(f"❌ Terjadi error saat memproses VCF: {e}")
        clear_session(msg.from_user.id)
        await state.clear()

# ==================== ADMIN COMMANDS ====================

@dp.message(Command("hapus_cache"))
async def hapus_cache_cmd(msg: Message, state: FSMContext):
    clear_session(msg.from_user.id)
    await state.clear()
    await msg.reply("🧹 Cache & file sementara untuk sesi kamu sudah dihapus dari server.")

@dp.message(Command("hapus_semua_cache"))
async def hapus_semua_cache_cmd(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.reply("❌ Kamu tidak punya izin menjalankan perintah ini.")
        return

    count = 0
    for folder in SESSIONS_DIR.glob("*"):
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
            count += 1

    await msg.reply(f"🧹 Semua cache ({count} user) sudah dihapus dari server.")

@dp.message(Command("vpsinfo"))
async def vpsinfo_cmd(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.reply("❌ Kamu tidak punya izin menjalankan perintah ini.")
        return
    
    try:
        disk_info = get_disk_usage()
        
        info_text = f"""
🖥️ **INFORMASI VPS**

💾 **Disk Usage:**
📊 {disk_info['progress_bar']} {disk_info['usage_percent']:.1f}%

📈 **Total:** {disk_info['total_gb']:.1f} GB
📊 **Terpakai:** {disk_info['used_gb']:.1f} GB  
📉 **Tersisa:** {disk_info['free_gb']:.1f} GB

⏰ **Waktu Check:** {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}
        """
        
        await msg.reply(info_text)
        
    except Exception as e:
        await msg.reply(f"❌ Error mengambil info VPS: {e}")

@dp.message(Command("donasi"))
async def donasi_cmd(msg: Message):
    try:
        # Coba kirim foto QRIS jika file ada
        if Path(QRIS_PATH).exists():
            photo = FSInputFile(QRIS_PATH)
            caption_text = f"""
💰 **DONASI UNTUK BOT**

{DONASI_INFO}

{BANK_INFO}

Atau scan QRIS di atas! 📱

Terima kasih atas dukungan Anda! 🙏❤️
            """
            
            await msg.answer_photo(
                photo=photo,
                caption=caption_text,
                reply_markup=create_donasi_keyboard()
            )
        else:
            # Jika file QRIS tidak ada, kirim teks saja
            donate_text = f"""
💰 **DONASI UNTUK BOT**

{DONASI_INFO}

{BANK_INFO}

Terima kasih atas dukungan Anda! 🙏❤️
            """
            await msg.answer(donate_text, reply_markup=create_donasi_keyboard())
            
    except Exception as e:
        await msg.answer(
            f"💰 **DONASI UNTUK BOT**\n\n{DONASI_INFO}\n\n{BANK_INFO}\n\nTerima kasih atas dukungan Anda! 🙏❤️",
            reply_markup=create_donasi_keyboard()
        )

@dp.message(Command("help"))
async def help_cmd(msg: Message):
    help_text = """
📋 **CARA PENGGUNAAN BOT**

🔹 **TXT → VCF (Teks ke Kontak)**
1️⃣ Ketik /start dan pilih "📄 TXT→VCF"
2️⃣ Upload file .txt berisi nomor telepon (satu nomor per baris)
3️⃣ Ketik /konfirmasi setelah selesai upload
4️⃣ Masukkan nama kontak dasar (contoh: "Customer")
5️⃣ Masukkan nama file output (contoh: "HKSIANG")
6️⃣ Tentukan jumlah kontak per file VCF (contoh: 50)
7️⃣ Bot akan memproses dan mengirim file VCF

🔹 **VCF → TXT (Kontak ke Teks)**
1️⃣ Ketik /start dan pilih "📇 VCF→TXT"
2️⃣ Upload file .vcf (kontak vCard)
3️⃣ Ketik /proses setelah selesai upload
4️⃣ Bot akan mengekstrak nomor telepon ke file .txt

📝 **Format Nomor yang Didukung:**
• Indonesia: +62, 08xx
• Malaysia: +60
• Singapura: +65
• Hong Kong: +852
• India: +91
• Dan negara lainnya...

💡 **Tips:**
• File akan otomatis dihapus setelah proses selesai
• Nomor duplikat akan dihilangkan otomatis
• Format nomor akan diseragamkan

❓ **Butuh bantuan?** Hubungi admin!

**Commands:**
/start - Menu utama
/help - Panduan penggunaan
/donasi - Info donasi
/hapus_cache - Hapus cache Anda

**Admin Commands:**
/vpsinfo - Info VPS
/hapus_semua_cache - Hapus semua cache
    """
    
    await msg.answer(help_text)

# ==================== ERROR HANDLERS ====================

@dp.message(F.document)
async def handle_unexpected_document(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await msg.reply(
            "📄 File diterima! Tapi Anda belum memilih mode konversi.\n\n"
            "Ketik /start untuk memilih apakah ingin:\n"
            "• 📄 TXT→VCF (konversi teks ke kontak)\n"
            "• 📇 VCF→TXT (ekstrak nomor dari kontak)"
        )
    else:
        await msg.reply("❌ File tidak sesuai dengan mode yang dipilih atau format tidak didukung.")

@dp.message()
async def handle_unexpected_message(msg: Message, state: FSMContext):
    current_state = await state.get_state()
    
    if current_state is None:
        await msg.reply(
            "👋 Halo! Ketik /start untuk menggunakan bot ini.\n\n"
            "🤖 **Fitur yang tersedia:**\n"
            "• 📄 TXT→VCF: Konversi nomor telepon ke kontak\n"
            "• 📇 VCF→TXT: Ekstrak nomor dari kontak\n"
            "• ℹ️ /help: Panduan penggunaan"
        )
    elif current_state in [UploadStates.collecting_txt.state, UploadStates.collecting_vcf.state]:
        mode = "TXT→VCF" if current_state == UploadStates.collecting_txt.state else "VCF→TXT"
        cmd = "/konfirmasi" if current_state == UploadStates.collecting_txt.state else "/proses"
        await msg.reply(f"📤 Mode {mode} aktif. Upload file dulu, lalu ketik {cmd}")
    else:
        await msg.reply("❓ Pesan tidak dimengerti. Silakan ikuti instruksi yang diberikan.")

async def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("❌ Set BOT_TOKEN di konfigurasi!")
    
    print("🤖 Bot starting...")
    print(f"📂 Sessions directory: {SESSIONS_DIR}")
    print(f"👑 Admin IDs: {ADMIN_IDS}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())