import customtkinter as ctk
from tkinter import filedialog, messagebox
from pathlib import Path
import urllib.parse
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTTextLineHorizontal, LTChar, LTAnno
from PyPDF2 import PdfReader
import statistics
import fitz  # PyMuPDF
from PIL import Image, ImageTk
import re
import os

# Configuration de l'apparence
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# === Extraction avancée ===
def extract_annotation_tokens(pdf_path):
    reader = PdfReader(str(pdf_path))
    annots_by_page = {}
    for p_index, page in enumerate(reader.pages):
        annots = page.get("/Annots", [])
        for a in annots:
            obj = a.get_object()
            if "/A" in obj and "/URI" in obj["/A"]:
                uri = obj["/A"]["/URI"]
                if "texexp=" in uri:
                    encoded = uri.split("texexp=")[-1]
                    decoded = urllib.parse.unquote_plus(encoded)
                    rect = obj.get("/Rect")
                    rect_f = None
                    if rect:
                        try:
                            rect_f = [float(x) for x in rect]
                        except Exception:
                            rect_f = None
                    cx = cy = None
                    if rect_f:
                        cx = (rect_f[0] + rect_f[2]) / 2.0
                        cy = (rect_f[1] + rect_f[3]) / 2.0
                    # Encadrer le LaTeX correctement avec \( ... \)
                    token = {
                        "text": f"\\({decoded}\\)",
                        "x": cx if cx is not None else 0.0,
                        "y": cy if cy is not None else 0.0,
                        "type": "annot"
                    }
                    annots_by_page.setdefault(p_index, []).append(token)
    return annots_by_page

def extract_text_tokens(pdf_path):
    pages_tokens = {}
    for p_index, page_layout in enumerate(extract_pages(str(pdf_path))):
        tokens = []
        for element in page_layout:
            if isinstance(element, LTTextContainer):
                for line in element:
                    if not isinstance(line, LTTextLineHorizontal):
                        continue
                    char_items = []
                    for obj in line:
                        if isinstance(obj, LTChar):
                            ch = obj.get_text()
                            x0, y0, x1, y1 = obj.bbox
                            char_items.append({"type": "char", "text": ch, "x0": x0, "x1": x1})
                        elif isinstance(obj, LTAnno):
                            char_items.append({"type": "anno", "text": obj.get_text()})
                    if not char_items:
                        continue
                    widths = [ci["x1"] - ci["x0"] for ci in char_items if
                              ci["type"] == "char" and (ci["x1"] - ci["x0"]) > 0]
                    avg_w = statistics.mean(widths) if widths else 3.0
                    words = []
                    cur_text = ""
                    cur_x = None
                    prev_x1 = None
                    for ci in char_items:
                        if ci["type"] == "anno":
                            if cur_text:
                                words.append({"text": cur_text, "x": cur_x})
                            cur_text = ""
                            cur_x = None
                            prev_x1 = None
                            words.append({"text": " ", "x": None})
                        else:
                            ch = ci["text"]
                            x0 = ci["x0"]
                            x1 = ci["x1"]
                            if cur_text == "":
                                cur_text = ch
                                cur_x = x0
                                prev_x1 = x1
                            else:
                                gap = x0 - prev_x1 if prev_x1 is not None else 0
                                if gap > (0.6 * avg_w):
                                    words.append({"text": cur_text, "x": cur_x})
                                    cur_text = ch
                                    cur_x = x0
                                    prev_x1 = x1
                                else:
                                    cur_text += ch
                                    prev_x1 = x1
                    if cur_text:
                        words.append({"text": cur_text, "x": cur_x})
                    x0, y0, x1, y1 = line.bbox
                    cy = (y0 + y1) / 2.0
                    for w in words:
                        text = w["text"]
                        if text.strip() == "":
                            tokens.append(
                                {"text": " ", "x": w["x"] if w["x"] is not None else 0.0, "y": cy, "type": "space"})
                        else:
                            tokens.append(
                                {"text": text, "x": w["x"] if w["x"] is not None else 0.0, "y": cy, "type": "text"})
        pages_tokens[p_index] = tokens
    return pages_tokens

def merge_tokens_and_annots(pages_text_tokens, annots_by_page):
    pages_merged = {}
    for p in sorted(set(list(pages_text_tokens.keys()) + list(annots_by_page.keys()))):
        text_tokens = pages_text_tokens.get(p, [])
        annots = annots_by_page.get(p, [])
        all_tokens = text_tokens + [{"text": a["text"], "x": a["x"], "y": a["y"], "type": "annot"} for a in annots]
        all_tokens_sorted = sorted(all_tokens, key=lambda it: (- (it.get("y", 0) or 0), it.get("x", 0) or 0))
        lines = []
        current_line = []
        current_y = None
        for tok in all_tokens_sorted:
            ty = tok.get("y", 0) or 0
            if current_y is None:
                current_y = ty
                current_line = [tok]
            else:
                if abs(ty - current_y) <= 5:
                    current_line.append(tok)
                else:
                    lines.append(current_line)
                    current_line = [tok]
                    current_y = ty
        if current_line:
            lines.append(current_line)
        page_lines_text = []
        for line in lines:
            line_sorted = sorted(line, key=lambda it: it.get("x", 0) or 0)
            parts = []
            for idx, it in enumerate(line_sorted):
                txt = it["text"]
                if parts and parts[-1].endswith(" ") and txt == " ":
                    continue
                if txt == " ":
                    if not parts or parts[-1].endswith(" "):
                        continue
                    parts.append(" ")
                    continue
                if parts:
                    prev = parts[-1]
                    if (prev and prev[-1] in "([{/+-") or (txt and txt[0] in ".,;:)]%'"):
                        parts.append(txt)
                    else:
                        parts.append(" " + txt)
                else:
                    parts.append(txt)
            line_text = "".join(parts).lstrip()
            page_lines_text.append(line_text)
        pages_merged[p] = "\n".join(page_lines_text)
    return pages_merged

# === Nettoyage et encadrement LaTeX ===
def clean_text(text):
    cleaned_lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "Moodle" in line or "review.php" in line:
            continue
        if re.search(r"(Tentative|Heure|Utilisateur)", line):
            continue
        if line in ["Correct", "Incorrect", "Partiellement correct"]:
            continue
        # Encadrer correctement les équations LaTeX avec \( ... \)
        line = re.sub(r"\$(.*?)\$", r"\\(\1\\)", line)
        # Nettoyage du barème
        m = re.search(r"sur (\d+(?:,\d+)?)", line)
        if m:
            cleaned_lines.append(f"Barème : {m.group(1)}")
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)

def split_questions(text):
    parts = re.split(r"(Question\s*\d+)", text, flags=re.IGNORECASE)
    questions = []
    for i in range(1, len(parts), 2):
        label = parts[i].strip()
        body = clean_text(parts[i + 1])
        questions.append((label, body))
    return questions

# === Interface Graphique ===
class QuizExtractorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Extracteur de Quiz Moodle - Par Mathéo")
        self.geometry("1600x900")
        self.minsize(1200, 700)

        # Variables
        self.zoom_factor = 1.0
        self.pdf_path = None
        self.pdf_images = []
        self.pdf_labels = []
        self.current_page = 0
        self.total_pages = 0
        self.doc = None

        # Grille principale
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        self.header = ctk.CTkFrame(self, height=60)
        self.header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=5)
        self.header.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(self.header, text="Extracteur de Quiz Moodle",
                                        font=ctk.CTkFont(size=24, weight="bold"))
        self.title_label.grid(row=0, column=0, sticky="w", padx=20)

        self.btn = ctk.CTkButton(self.header, text="Ouvrir un PDF", command=self.open_pdf,
                                 width=120, height=40, font=ctk.CTkFont(weight="bold"))
        self.btn.grid(row=0, column=1, sticky="e", padx=20)

        # Left frame
        self.left_frame = ctk.CTkFrame(self)
        self.left_frame.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=10)
        self.left_frame.grid_rowconfigure(1, weight=1)
        self.left_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.left_frame, text="Questions extraites",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="w", padx=20, pady=10)

        self.tabview = ctk.CTkTabview(self.left_frame)
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.tabview._segmented_button.configure(font=ctk.CTkFont(weight="bold"))

        # Right frame (PDF)
        self.right_frame = ctk.CTkFrame(self)
        self.right_frame.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=10)
        self.right_frame.grid_rowconfigure(2, weight=1)
        self.right_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.right_frame, text="Aperçu du PDF",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="w", padx=20, pady=10)

        # Toolbar PDF
        self.toolbar = ctk.CTkFrame(self.right_frame, height=40)
        self.toolbar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 5))
        self.toolbar.grid_columnconfigure(0, weight=1)
        self.toolbar.grid_columnconfigure(1, weight=1)

        self.nav_frame = ctk.CTkFrame(self.toolbar, fg_color="transparent")
        self.nav_frame.grid(row=0, column=0, sticky="w")

        self.first_btn = ctk.CTkButton(self.nav_frame, text="⏮", width=40, command=self.first_page)
        self.first_btn.grid(row=0, column=0, padx=2)
        self.prev_btn = ctk.CTkButton(self.nav_frame, text="◀", width=40, command=self.prev_page)
        self.prev_btn.grid(row=0, column=1, padx=2)
        self.page_label = ctk.CTkLabel(self.nav_frame, text="Page 0/0", width=80)
        self.page_label.grid(row=0, column=2, padx=2)
        self.next_btn = ctk.CTkButton(self.nav_frame, text="▶", width=40, command=self.next_page)
        self.next_btn.grid(row=0, column=3, padx=2)
        self.last_btn = ctk.CTkButton(self.nav_frame, text="⏭", width=40, command=self.last_page)
        self.last_btn.grid(row=0, column=4, padx=2)

        # Zoom
        self.zoom_frame = ctk.CTkFrame(self.toolbar, fg_color="transparent")
        self.zoom_frame.grid(row=0, column=1, sticky="e")
        self.zoom_out_btn = ctk.CTkButton(self.zoom_frame, text="➖", width=40, command=self.zoom_out)
        self.zoom_out_btn.grid(row=0, column=0, padx=2)
        self.zoom_label = ctk.CTkLabel(self.zoom_frame, text="100%", width=50)
        self.zoom_label.grid(row=0, column=1, padx=2)
        self.zoom_in_btn = ctk.CTkButton(self.zoom_frame, text="➕", width=40, command=self.zoom_in)
        self.zoom_in_btn.grid(row=0, column=2, padx=2)
        self.reset_zoom_btn = ctk.CTkButton(self.zoom_frame, text="🔍", width=40, command=self.reset_zoom)
        self.reset_zoom_btn.grid(row=0, column=3, padx=2)

        # Canvas PDF
        self.pdf_canvas_frame = ctk.CTkFrame(self.right_frame)
        self.pdf_canvas_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.pdf_canvas_frame.grid_rowconfigure(0, weight=1)
        self.pdf_canvas_frame.grid_columnconfigure(0, weight=1)

        self.v_scroll = ctk.CTkScrollbar(self.pdf_canvas_frame, orientation="vertical")
        self.v_scroll.grid(row=0, column=1, sticky="ns")
        self.h_scroll = ctk.CTkScrollbar(self.pdf_canvas_frame, orientation="horizontal")
        self.h_scroll.grid(row=1, column=0, sticky="ew")

        self.pdf_canvas = ctk.CTkCanvas(self.pdf_canvas_frame, bg="gray20",
                                        yscrollcommand=self.v_scroll.set,
                                        xscrollcommand=self.h_scroll.set,
                                        highlightthickness=0)
        self.pdf_canvas.grid(row=0, column=0, sticky="nsew")
        self.v_scroll.configure(command=self.pdf_canvas.yview)
        self.h_scroll.configure(command=self.pdf_canvas.xview)

        # Windows / Mac
        self.pdf_canvas.bind_all("<MouseWheel>", self.on_mousewheel)
        # Linux
        self.pdf_canvas.bind_all("<Button-4>", self.on_mousewheel)
        self.pdf_canvas.bind_all("<Button-5>", self.on_mousewheel)

        self.pdf_inner_frame = ctk.CTkFrame(self.pdf_canvas)
        self.pdf_window = self.pdf_canvas.create_window((0, 0), window=self.pdf_inner_frame, anchor="nw")
        self.pdf_canvas.bind("<Configure>", self.on_canvas_configure)

        self.status_bar = ctk.CTkLabel(self, text="Prêt - Aucun PDF chargé", height=30,
                                       font=ctk.CTkFont(size=12), anchor="w")
        self.status_bar.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 5))

        self.update_navigation_buttons()

    def update_status(self, message):
        self.status_bar.configure(text=message)
        self.update_idletasks()

    def update_navigation_buttons(self):
        state = "normal" if self.doc else "disabled"
        for btn in [self.first_btn, self.prev_btn, self.next_btn, self.last_btn,
                    self.zoom_in_btn, self.zoom_out_btn, self.reset_zoom_btn]:
            btn.configure(state=state)

    # === PDF ===
    def open_pdf(self):
        file_path = filedialog.askopenfilename(filetypes=[("Fichiers PDF", "*.pdf")])
        if not file_path:
            return
        self.pdf_path = file_path
        self.update_status(f"Chargement du PDF: {os.path.basename(file_path)}...")
        try:
            annots = extract_annotation_tokens(file_path)
            text_tokens = extract_text_tokens(file_path)
            merged = merge_tokens_and_annots(text_tokens, annots)
            final_pages = [merged[p] for p in sorted(merged.keys())]
            final_text = "\n\n".join(final_pages)
            questions = split_questions(final_text)

            for tab in self.tabview._name_list:
                self.tabview.delete(tab)

            for label, body in questions:
                m = re.search(r"Barème : (\d+(?:,\d+)?)", body)
                score = m.group(1) if m else "N/A"
                tab_name = label.replace("Question", "Q").strip()
                tab = self.tabview.add(tab_name)

                content_frame = ctk.CTkFrame(tab, fg_color="transparent")
                content_frame.pack(fill="both", expand=True, padx=5, pady=5)
                content_frame.grid_rowconfigure(1, weight=1)
                content_frame.grid_columnconfigure(0, weight=1)

                score_frame = ctk.CTkFrame(content_frame, height=40)
                score_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
                score_frame.grid_columnconfigure(0, weight=1)

                score_label = ctk.CTkLabel(score_frame, text=f"Barème: {score}",
                                           font=ctk.CTkFont(weight="bold"),
                                           fg_color="gray25", corner_radius=5)
                score_label.grid(row=0, column=0, sticky="w", padx=5, pady=5)

                copy_btn = ctk.CTkButton(score_frame, text="Copier", width=80,
                                         command=lambda b=body: self.copy_to_clipboard(b))
                copy_btn.grid(row=0, column=1, sticky="e", padx=5, pady=5)

                text_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
                text_frame.grid(row=1, column=0, sticky="nsew")
                text_frame.grid_rowconfigure(0, weight=1)
                text_frame.grid_columnconfigure(0, weight=1)

                text_scroll = ctk.CTkScrollbar(text_frame)
                text_scroll.grid(row=0, column=1, sticky="ns")

                textbox = ctk.CTkTextbox(text_frame, wrap="word", font=("Arial", 14),
                                         yscrollcommand=text_scroll.set)
                textbox.insert("1.0", body)
                textbox.configure(state="disabled")
                textbox.grid(row=0, column=0, sticky="nsew")

                text_scroll.configure(command=textbox.yview)

            self.show_pdf()
            self.update_status(f"Prêt - {len(questions)} questions extraites de {os.path.basename(file_path)}")
        except Exception as e:
            messagebox.showerror("Erreur", f"Une erreur s'est produite: {str(e)}")
            self.update_status("Erreur lors du chargement du PDF")

    def show_pdf(self):
        if not self.pdf_path:
            return
        if self.doc:
            self.doc.close()
        for widget in self.pdf_inner_frame.winfo_children():
            widget.destroy()
        self.pdf_images = []
        self.doc = fitz.open(self.pdf_path)
        self.total_pages = len(self.doc)
        self.current_page = 0
        self.display_page(0)
        self.update_navigation_buttons()

    def display_page(self, page_num):
        if not self.doc or page_num < 0 or page_num >= self.total_pages:
            return
        self.current_page = page_num
        self.page_label.configure(text=f"Page {page_num + 1}/{self.total_pages}")
        for widget in self.pdf_inner_frame.winfo_children():
            widget.destroy()
        self.pdf_images = []

        page = self.doc.load_page(page_num)
        pix = page.get_pixmap()
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        w, h = img.size
        new_w, new_h = int(w * self.zoom_factor), int(h * self.zoom_factor)
        img = img.resize((new_w, new_h))
        img_tk = ImageTk.PhotoImage(img)
        self.pdf_images.append(img_tk)
        label = ctk.CTkLabel(self.pdf_inner_frame, image=img_tk, text="")
        label.pack()
        self.pdf_inner_frame.update_idletasks()
        self.pdf_canvas.configure(scrollregion=self.pdf_canvas.bbox("all"))
        self.zoom_label.configure(text=f"{int(self.zoom_factor * 100)}%")

    def zoom_in(self):
        self.zoom_factor *= 1.2
        self.display_page(self.current_page)

    def zoom_out(self):
        self.zoom_factor /= 1.2
        self.display_page(self.current_page)

    def reset_zoom(self):
        self.zoom_factor = 1.0
        self.display_page(self.current_page)

    def first_page(self):
        self.display_page(0)

    def last_page(self):
        self.display_page(self.total_pages - 1)

    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.display_page(self.current_page + 1)

    def prev_page(self):
        if self.current_page > 0:
            self.display_page(self.current_page - 1)

    # === Remplacer la fonction on_mousewheel ===
    def on_mousewheel(self, event):
        shift_pressed = (event.state & 0x0001) != 0  # Shift enfoncé
        if event.num == 4 or event.delta > 0:  # Scroll up
            delta = -1
        elif event.num == 5 or event.delta < 0:  # Scroll down
            delta = 1
        else:
            delta = 0

        if shift_pressed:  # Scroll horizontal
            self.pdf_canvas.xview_scroll(delta, "units")
        else:  # Scroll vertical
            self.pdf_canvas.yview_scroll(delta, "units")

    def on_canvas_configure(self, event):
        self.pdf_canvas.configure(scrollregion=self.pdf_canvas.bbox("all"))

    def copy_to_clipboard(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_status("Question copiée dans le presse-papiers")

if __name__ == "__main__":
    app = QuizExtractorApp()
    app.mainloop()
