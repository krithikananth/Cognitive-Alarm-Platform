from fpdf import FPDF
import os

class PDFReport(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=False, margin=10)

    def footer(self):
        self.set_y(-10)
        self.set_font('Times', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f'{self.page_no()}', align='C')

    def section_title(self, num, title):
        self.set_font('Times', 'B', 14)
        self.set_text_color(0, 51, 102)
        self.cell(0, 7, f'{num}. {title}', new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(0, 51, 102)
        self.set_line_width(0.8)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def body(self, text):
        self.set_font('Times', '', 10)
        self.set_text_color(0, 0, 0)
        self.multi_cell(0, 4.5, text)
        self.ln(1)

    def bold_body(self, bold_part, normal_part):
        self.set_font('Times', 'B', 10)
        self.set_text_color(0, 0, 0)
        self.write(4.5, bold_part)
        self.set_font('Times', '', 10)
        self.write(4.5, normal_part)
        self.ln(5)

    def bullet(self, bold_prefix, text):
        self.set_font('Times', 'B', 10)
        self.set_text_color(0, 0, 0)
        x = self.get_x()
        self.cell(4, 4.5, '-')
        self.write(4.5, bold_prefix)
        self.set_font('Times', '', 10)
        rw = self.w - self.get_x() - self.r_margin
        self.multi_cell(rw, 4.5, text)
        self.ln(1)

    def highlight_box(self, title, text):
        self.set_fill_color(240, 245, 255)
        self.set_draw_color(0, 102, 204)
        x, y = self.l_margin, self.get_y()
        w = self.w - self.l_margin - self.r_margin
        
        self.set_font('Times', 'B', 10)
        title_lines = self.multi_cell(w - 6, 4.5, title, dry_run=True, output="LINES")
        self.set_font('Times', 'I', 9.5)
        text_lines = self.multi_cell(w - 6, 4.5, text, dry_run=True, output="LINES")
        
        h = (len(title_lines) + len(text_lines)) * 4.5 + 6
        self.set_line_width(1)
        self.line(x, y, x, y + h)
        self.rect(x, y, w, h, style='F')
        
        self.set_xy(x + 4, y + 3)
        self.set_font('Times', 'B', 10)
        self.set_text_color(0, 51, 102)
        self.multi_cell(w - 6, 4.5, title)
        
        self.set_x(x + 4)
        self.set_font('Times', 'I', 9.5)
        self.set_text_color(30, 30, 30)
        self.multi_cell(w - 6, 4.5, text)
        self.set_y(y + h + 3)
        self.set_line_width(0.3)

    def add_table(self, headers, rows, col_widths=None):
        total_w = self.w - self.l_margin - self.r_margin
        if not col_widths:
            col_widths = [total_w / len(headers)] * len(headers)
            
        self.set_draw_color(150, 150, 150)
        self.set_line_width(0.3)

        def draw_row(data, is_header=False, row_idx=0):
            max_h = 0
            if is_header:
                self.set_font('Times', 'B', 9)
            else:
                self.set_font('Times', '', 9)
            
            for i, txt in enumerate(data):
                lines = self.multi_cell(col_widths[i] - 2, 5, txt, dry_run=True, output="LINES")
                h = len(lines) * 5 + 2
                if h > max_h:
                    max_h = h
            
            if self.get_y() + max_h > self.h - self.b_margin:
                self.add_page()
                
            y = self.get_y()
            
            if is_header:
                self.set_fill_color(0, 51, 102)
                self.set_text_color(255, 255, 255)
            else:
                self.set_text_color(0, 0, 0)
                if row_idx % 2 == 0:
                    self.set_fill_color(245, 245, 250)
                else:
                    self.set_fill_color(255, 255, 255)
                    
            for i, txt in enumerate(data):
                x = self.get_x()
                self.rect(x, y, col_widths[i], max_h, style='DF')
                self.set_xy(x + 1, y + 1)
                self.multi_cell(col_widths[i] - 2, 5, txt, align='L', border=0)
                self.set_xy(x + col_widths[i], y)
            self.set_y(y + max_h)

        draw_row(headers, is_header=True)
        for ri, row in enumerate(rows):
            draw_row(row, is_header=False, row_idx=ri)
        self.ln(3)


def generate_pdf():
    pdf = PDFReport()
    pw = 210 - 20 - 20  # usable page width

    # ==================== PAGE 1 ====================
    pdf.add_page()
    pdf.set_left_margin(20)
    pdf.set_right_margin(20)
    pdf.set_y(15)

    # TITLE
    pdf.set_font('Times', 'B', 20)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, 'AI-Powered Product Understanding System', align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.set_font('Times', 'B', 11)
    pdf.set_text_color(0, 102, 204)
    pdf.cell(0, 6, 'Designing Intelligent Vision-Language AI for Amazon / Flipkart', align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # --- SECTION 1 ---
    pdf.section_title("1", "Inputs (What The Model Sees)")
    pdf.bold_body("The Core Signal: Product Image. ", "A single photo of a sneaker encodes brand, style, material, and demographics instantly. Visual features offer high reliability, whereas seller-written descriptions are often spammy or inaccurate.")
    pdf.bullet("Quality First (Preprocessing): ", "Garbage in = Garbage out. We run a lightweight background remover and blur-detector before the image ever hits the heavy AI. Bad images are rejected immediately.")
    pdf.highlight_box("Clear Thinking Principle:", "Always trust visual evidence over human input in e-commerce. If available, we fuse the image with basic catalog metadata (like 'price' or 'seller category') for context, but the image is the primary source of information.")

    # --- SECTION 2 ---
    pdf.section_title("2", "Outputs (What The Model Generates)")
    pdf.bold_body("Output A: Hierarchical Category Path. ", "We don't predict a simple 'Shoes' label. We predict the full taxonomy: Fashion > Footwear > Men's > Running.")
    pdf.bullet("Why Hierarchy? ", "The search engine needs the leaf node ('Running'), but the analytics dashboard needs the root node ('Fashion').")
    
    pdf.bold_body("Output B: Natural Language Description. ", "A fluid, human-readable paragraph generated directly from the visual features of the image.")
    
    pdf.highlight_box("Real-World Output Example:", "Category: Electronics > Audio > Headphones > Over-Ear\nDescription: \"Premium wireless over-ear headphones in matte black. Features active noise cancellation, plush memory foam ear cushions for all-day comfort, and sleek metal headband accents. Ideal for travel and audiophiles.\"")

    # --- SECTION 3 ---
    pdf.section_title("3", "Model Selection (The Brain)")
    pdf.body("We need a system that understands images and speaks language. A traditional CNN classifier is too rigid (can't generate descriptions, requires retraining for new categories). We need a Multimodal Vision-Language Model (VLM).")

    cw3 = [pw*0.25, pw*0.75]
    pdf.add_table(["Model Component", "Why It's The Best Choice"],
        [["CLIP (Classification)", "Zero-Shot. It compares image embeddings to category text embeddings instantly. We can add 1,000 new categories tomorrow without retraining the model."],
         ["BLIP-2 (Description)", "A widely used vision-language model for image captioning. It uses a lightweight bridge to translate visual features into text. We fine-tune it on our existing catalog."],
         ["Shared Backbone", "Cost-effective. Both models share the same Vision Transformer (ViT) encoder. We process the image once, and feed it to both heads."]], cw3)

    pdf.highlight_box("The 'Clear Thinking' Choice:", "Don't build one massive slow model. Use a shared visual backbone that splits into a fast matcher (CLIP) for categorization, and a generative head (BLIP-2) for descriptions.")

    # ==================== PAGE 2 ====================
    pdf.add_page()
    pdf.set_left_margin(20)
    pdf.set_right_margin(20)
    pdf.set_y(15)

    # --- SECTION 4 ---
    pdf.section_title("4", "System Design (The Pipeline)")

    # Professional Flowchart
    start_y = pdf.get_y() + 3
    
    def draw_box(x, y, w, h, title, subtitle="", bg=(245, 248, 255)):
        pdf.set_fill_color(*bg)
        pdf.set_draw_color(0, 51, 102)
        pdf.set_line_width(0.4)
        pdf.rect(x, y, w, h, style='DF')
        
        pdf.set_font('Times', 'B', 9)
        pdf.set_text_color(0, 30, 70)
        if subtitle:
            pdf.set_xy(x, y + h/2 - 3.5)
            pdf.cell(w, 4, title, align='C')
            pdf.set_xy(x, y + h/2)
            pdf.set_font('Times', '', 8)
            pdf.set_text_color(50, 50, 50)
            pdf.cell(w, 4, subtitle, align='C')
        else:
            pdf.set_xy(x, y + h/2 - 2)
            pdf.cell(w, 4, title, align='C')
            
    def arrow_down(x, y1, y2):
        pdf.set_draw_color(0, 51, 102)
        pdf.set_line_width(0.4)
        pdf.line(x, y1, x, y2)
        pdf.line(x, y2, x - 1.2, y2 - 1.5)
        pdf.line(x, y2, x + 1.2, y2 - 1.5)

    cx = 105
    y = start_y
    draw_box(cx - 30, y, 60, 7, "Seller Uploads Image", bg=(235, 240, 250))
    arrow_down(cx, y+7, y+12)
    
    y += 12
    draw_box(cx - 50, y, 100, 9, "1. PRE-PROCESSING QA", "Resize | Remove Background")
    
    pdf.set_font('Times', 'I', 8)
    pdf.set_text_color(80, 80, 80)
    pdf.set_xy(cx + 2, y + 10)
    pdf.cell(30, 3, "(Passes QA)")
    arrow_down(cx, y+9, y+15)
    
    y += 15
    draw_box(cx - 50, y, 100, 9, "2. VISUAL ENCODER", "Extract dense visual features (ViT)")
    
    pdf.set_draw_color(0, 51, 102)
    pdf.set_line_width(0.4)
    pdf.line(cx, y+9, cx, y+12)
    pdf.line(cx - 37, y+12, cx + 37, y+12)
    arrow_down(cx - 37, y+12, y+16)
    arrow_down(cx + 37, y+12, y+16)
    
    y += 16
    draw_box(cx - 72, y, 70, 9, "3A. CLIP-BASED CATEGORY MATCHER", "Matches category path")
    draw_box(cx + 2, y, 70, 9, "3B. BLIP-2 GENERATOR", "Writes full description")
    
    pdf.set_draw_color(0, 51, 102)
    pdf.set_line_width(0.4)
    pdf.line(cx - 37, y+9, cx - 37, y+12)
    pdf.line(cx + 37, y+9, cx + 37, y+12)
    pdf.line(cx - 37, y+12, cx + 37, y+12)
    arrow_down(cx, y+12, y+16)
    
    y += 16
    draw_box(cx - 65, y, 130, 10, "4. CONFIDENCE ROUTER (The Safety Net)", "High Confidence (>85%) -> Auto-Publish   |   Low Confidence (<85%) -> Route to Human QA")
    
    pdf.set_y(y + 14)
    
    pdf.highlight_box("The Secret Sauce: The Feedback Loop.", "When a human QA corrects a low-confidence prediction, that data is logged. We periodically retrain the model on these corrections. The system continuously teaches itself.")

    # --- SECTION 5 ---
    pdf.section_title("5", "Evaluation (How We Know It's Good)")
    pdf.bold_body("1. Automated Metrics (Run on every code change):", "")
    pdf.bullet("Accuracy: ", "Top-1 and Top-3 Categorization Accuracy.")
    pdf.bullet("Classification Metrics: ", "Precision, Recall, and F1-score for comprehensive evaluation.")
    pdf.bullet("Text Quality: ", "BLEU and ROUGE scores to measure how closely the generated text matches human-written gold standards.")
    
    pdf.bold_body("2. Human Evaluation (The Ultimate Truth):", "")
    pdf.body("Automated metrics can be gamed. Every week, human reviewers audit 100 random products to grade Factual Correctness (no hallucinations), Fluency, and Purchase Intent.")

    # --- SECTION 6 ---
    pdf.section_title("6", "Business Value (Why It Matters)")
    
    cw6 = [pw*0.3, pw*0.7]
    pdf.add_table(["Business Driver", "The Real-World Impact"],
        [["Frictionless Selling", "Sellers just upload a photo. Cataloging time is significantly reduced, enabling faster product onboarding. More listings = More revenue."],
         ["Higher Conversion", "Rich, accurate, SEO-optimized descriptions drive a lift in buyer conversion rates."],
         ["Operational Savings", "Automates a large portion of manual catalog quality assurance, saving operational overhead annually."]], cw6)

    # --- BONUS ---
    pdf.section_title("Bonus", "Real-World Application: Amazon")
    
    pdf.highlight_box("Amazon's 'AutoKnowledge' & 'StyleSnap'", 
        "Amazon uses multimodal AI to extract product attributes from images and improve visual search experiences such as StyleSnap. \n\n"
        "How they use it: If a seller uploads a blue striped shirt but forgets to write 'striped', the AI tags it anyway. This powers 'StyleSnap', where users take a photo of an outfit and the AI finds visually similar products.")



    # Save
    out = r"f:\intelligent-cognitive-alarm\AI_Product_Understanding_System.pdf"
    pdf.output(out)
    print(f"PDF generated: {out}")
    print(f"Size: {os.path.getsize(out)/1024:.1f} KB | Pages: 2")

if __name__ == "__main__":
    generate_pdf()
