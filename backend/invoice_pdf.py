"""Invoice PDF Generator — uses invoice template settings"""
from fpdf import FPDF
from datetime import datetime
import os


def hex_to_rgb(hex_color):
    """Convert hex color (#8c8c8c) to RGB tuple"""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        return (30, 64, 175)  # default blue
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def generate_invoice_pdf(invoice: dict, user: dict, items: list = None, settings: dict = None, order: dict = None) -> bytes:
    """Generate invoice PDF using the admin's invoice template settings"""
    
    inv_settings = (settings or {}).get("invoice", {})
    branding = (settings or {}).get("branding", {})
    
    # Company info from invoice settings, fallback to branding
    company_name = inv_settings.get("company_name") or branding.get("site_name", "Billing System")
    company_email = inv_settings.get("company_email") or ""
    company_address = inv_settings.get("company_address") or ""
    company_phone = inv_settings.get("company_phone") or ""
    company_website = inv_settings.get("company_website") or ""
    
    # Colors
    primary_color = hex_to_rgb(inv_settings.get("primary_color", "#1e40af"))
    accent_color = hex_to_rgb(inv_settings.get("accent_color", "#f3f4f6"))
    
    # Custom content
    payment_instructions = inv_settings.get("payment_instructions") or inv_settings.get("notes") or ""
    thank_you = inv_settings.get("thank_you_message") or ""
    footer_text = inv_settings.get("footer_text") or ""
    
    currency_symbol = "$"
    
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    
    # ===== HEADER WITH LOGO =====
    logo_url = inv_settings.get("logo_url") or branding.get("logo_url") or ""
    header_y = pdf.get_y()
    
    if logo_url:
        try:
            import tempfile, urllib.request, ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(logo_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                img_data = resp.read()
            ext = ".png"
            if ".jpg" in logo_url.lower() or ".jpeg" in logo_url.lower():
                ext = ".jpg"
            tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            tmp.write(img_data)
            tmp.close()
            # Logo only, no company name text — logo replaces the name
            pdf.image(tmp.name, x=10, y=header_y, h=14)
            os.unlink(tmp.name)
        except Exception as logo_err:
            import logging
            logging.getLogger(__name__).warning(f"Failed to add logo to invoice: {logo_err}")
            pdf.set_font("Helvetica", "B", 22)
            pdf.set_text_color(*primary_color)
            pdf.cell(95, 12, company_name)
    else:
        pdf.set_font("Helvetica", "B", 22)
        pdf.set_text_color(*primary_color)
        pdf.cell(95, 12, company_name)
    
    pdf.set_xy(105, header_y)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(95, 14, "INVOICE", align="R")
    pdf.set_y(header_y + 16)
    
    pdf.set_draw_color(*primary_color)
    pdf.set_line_width(0.5)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(8)
    
    # ===== COMPANY & CUSTOMER INFO =====
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(95, 5, "FROM")
    pdf.cell(95, 5, "BILL TO")
    pdf.ln(6)
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(50, 50, 50)
    
    # From (company)
    pdf.cell(95, 5, company_name)
    # Bill to (customer)
    customer_name = user.get("name", "N/A") if user else "N/A"
    customer_email = user.get("email", "") if user else ""
    pdf.cell(95, 5, customer_name)
    pdf.ln(5)
    
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(80, 80, 80)
    
    company_lines = [company_email, company_phone, company_address, company_website]
    customer_lines = [customer_email, "", "", ""]
    
    for i in range(4):
        cl = company_lines[i] if i < len(company_lines) else ""
        cu = customer_lines[i] if i < len(customer_lines) else ""
        if cl or cu:
            pdf.cell(95, 4.5, cl)
            pdf.cell(95, 4.5, cu)
            pdf.ln(4.5)
    
    pdf.ln(6)
    
    # ===== INVOICE DETAILS =====
    inv_number = invoice.get("invoice_number", "N/A")
    created = invoice.get("created_at")
    created_str = created.strftime("%B %d, %Y") if isinstance(created, datetime) else str(created)[:10] if created else "N/A"
    due = invoice.get("due_date")
    due_str = due.strftime("%B %d, %Y") if isinstance(due, datetime) else str(due)[:10] if due else "N/A"
    status = invoice.get("status", "pending").upper()
    
    # Details box with accent color background
    pdf.set_fill_color(*accent_color)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(50, 50, 50)
    
    details = [
        ("Invoice #:", inv_number),
        ("Date:", created_str),
        ("Due Date:", due_str),
        ("Status:", status),
    ]
    
    for label, value in details:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(25, 6, label)
        pdf.set_font("Helvetica", "", 10)
        if label == "Status:":
            if status == "PAID":
                pdf.set_text_color(22, 163, 74)
            elif status == "PENDING":
                pdf.set_text_color(202, 138, 4)
            else:
                pdf.set_text_color(220, 38, 38)
            pdf.set_font("Helvetica", "B", 10)
        pdf.cell(70, 6, str(value))
        pdf.set_text_color(50, 50, 50)
        pdf.ln(6)
    
    pdf.ln(8)
    
    # ===== ITEMS TABLE =====
    pdf.set_fill_color(*primary_color)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(100, 8, "  Description", 0, 0, "L", True)
    pdf.cell(30, 8, "Qty", 0, 0, "C", True)
    pdf.cell(30, 8, "Price", 0, 0, "R", True)
    pdf.cell(30, 8, "Total  ", 0, 0, "R", True)
    pdf.ln()
    
    pdf.set_text_color(50, 50, 50)
    total = 0
    
    if items:
        for i, item in enumerate(items):
            if i % 2 == 0:
                pdf.set_fill_color(*accent_color)
            else:
                pdf.set_fill_color(255, 255, 255)
            
            name = item.get("product_name", "Service")
            qty = max(1, int(item.get("quantity") or 1))
            price = item.get("price", 0)
            line_total = price * qty
            total += line_total
            
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(100, 7, f"  {name}", 0, 0, "L", True)
            pdf.cell(30, 7, str(qty), 0, 0, "C", True)
            pdf.cell(30, 7, f"{currency_symbol}{price:.2f}", 0, 0, "R", True)
            pdf.cell(30, 7, f"{currency_symbol}{line_total:.2f}  ", 0, 0, "R", True)
            pdf.ln()
    else:
        desc = invoice.get("description", "Service charge")
        pdf.set_fill_color(*accent_color)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(100, 7, f"  {desc}", 0, 0, "L", True)
        pdf.cell(30, 7, "1", 0, 0, "C", True)
        pdf.cell(30, 7, f"{currency_symbol}{invoice.get('total', 0):.2f}", 0, 0, "R", True)
        pdf.cell(30, 7, f"{currency_symbol}{invoice.get('total', 0):.2f}  ", 0, 0, "R", True)
        pdf.ln()
        total = invoice.get("total", 0)

    shipping_cost = float((order or {}).get("shipping_cost") or 0) if isinstance(order, dict) else 0.0
    if shipping_cost > 0:
        method = (order.get("shipping_method") or {}) if isinstance(order, dict) else {}
        label = f"Shipping - {method.get('service_name', '')}".strip(" -")
        pdf.set_fill_color(255, 255, 255)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(100, 7, f"  {label}", 0, 0, "L", True)
        pdf.cell(30, 7, "1", 0, 0, "C", True)
        pdf.cell(30, 7, f"{currency_symbol}{shipping_cost:.2f}", 0, 0, "R", True)
        pdf.cell(30, 7, f"{currency_symbol}{shipping_cost:.2f}  ", 0, 0, "R", True)
        pdf.ln()
        total += shipping_cost
    
    # ===== TOTALS =====
    pdf.ln(4)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(130, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)
    
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(130, 7, "")
    pdf.cell(30, 7, "Total:", 0, 0, "R")
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*primary_color)
    pdf.cell(30, 7, f"{currency_symbol}{invoice.get('total', total):.2f}  ", 0, 0, "R")
    pdf.ln(10)
    
    # ===== STATUS BADGE =====
    if status == "PAID":
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(22, 163, 74)
        pdf.cell(0, 10, "PAID", align="R")
        pdf.ln(6)
    elif status == "PENDING":
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(202, 138, 4)
        pdf.cell(0, 10, "PAYMENT DUE", align="R")
        pdf.ln(6)
    
    # ===== PAYMENT INSTRUCTIONS =====
    if payment_instructions and status != "PAID":
        pdf.ln(6)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(50, 50, 50)
        pdf.cell(0, 6, "Payment Instructions")
        pdf.ln(6)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(190, 4.5, payment_instructions)
    
    # ===== THANK YOU =====
    if thank_you:
        pdf.ln(6)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(100, 100, 100)
        pdf.multi_cell(190, 4.5, thank_you)
    
    # ===== FOOTER =====
    pdf.ln(10)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(150, 150, 150)
    
    if footer_text:
        pdf.cell(0, 5, footer_text, align="C")
    else:
        pdf.cell(0, 5, f"Generated by {company_name} on {datetime.utcnow().strftime('%B %d, %Y')}", align="C")
    
    return pdf.output()
