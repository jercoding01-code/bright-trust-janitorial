import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#6b7280"))
        
        # Header banner on pages > 1
        if self._pageNumber > 1:
            self.drawString(54, 750, "Bright Trust Janitorial Inc. — Administrator Operations & User Guide")
            self.setStrokeColor(colors.HexColor("#e5e7eb"))
            self.setLineWidth(0.5)
            self.line(54, 742, 558, 742)
            
        # Footer page number
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 36, page_text)
        self.drawString(54, 36, "CONFIDENTIAL & PROPRIETARY — BRIGHT TRUST JANITORIAL INC.")
        self.setStrokeColor(colors.HexColor("#e5e7eb"))
        self.setLineWidth(0.5)
        self.line(54, 48, 558, 48)
        
        self.restoreState()

def create_admin_manual_pdf(filename):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )
    
    styles = getSampleStyleSheet()
    
    # Custom Brand Palette
    NAVY = colors.HexColor("#1f2937")
    BLUE = colors.HexColor("#2774AE")
    GOLD = colors.HexColor("#d97706")
    GREEN = colors.HexColor("#059669")
    DARK = colors.HexColor("#111827")
    GRAY = colors.HexColor("#4b5563")
    LIGHT_BG = colors.HexColor("#f9fafb")
    BORDER_COLOR = colors.HexColor("#e5e7eb")
    
    # Modify / Create Paragraph Styles
    title_style = ParagraphStyle(
        'CoverTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=NAVY,
        alignment=0,
        spaceAfter=10
    )
    
    subtitle_style = ParagraphStyle(
        'CoverSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        leading=16,
        textColor=BLUE,
        spaceAfter=25
    )
    
    h1_style = ParagraphStyle(
        'SectionH1',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        textColor=NAVY,
        spaceBefore=18,
        spaceAfter=10,
        keepWithNext=True
    )
    
    h2_style = ParagraphStyle(
        'SectionH2',
        parent=styles['Heading3'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        textColor=BLUE,
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'BodyTextCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=DARK,
        spaceAfter=8
    )
    
    bullet_style = ParagraphStyle(
        'BulletCustom',
        parent=body_style,
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=5
    )
    
    code_style = ParagraphStyle(
        'CodeSnippet',
        parent=body_style,
        fontName='Courier',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#1e293b"),
        backColor=colors.HexColor("#f1f5f9"),
        borderColor=colors.HexColor("#cbd5e1"),
        borderWidth=1,
        borderPadding=6,
        spaceAfter=10
    )
    
    callout_style = ParagraphStyle(
        'CalloutText',
        parent=body_style,
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor("#1e3a8a"),
        backColor=colors.HexColor("#eff6ff"),
        borderColor=colors.HexColor("#93c5fd"),
        borderWidth=1,
        borderPadding=8,
        spaceAfter=12
    )

    story = []
    
    # ------------------ COVER HEADER ------------------
    story.append(Paragraph("BRIGHT TRUST JANITORIAL INC.", ParagraphStyle('BrandHeader', fontName='Helvetica-Bold', fontSize=12, textColor=GOLD, spaceAfter=4)))
    story.append(Paragraph("Administrator Operations & User Guide", title_style))
    story.append(Paragraph("Complete Operating Instructions for Management, Booking Scheduling, Cleaner Staff Dispatch, Financial Reconciliation & CRA Compliance", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=2, color=BLUE, spaceAfter=20))
    
    # ------------------ 1. SYSTEM OVERVIEW ------------------
    story.append(Paragraph("1. System Overview & Core Capabilities", h1_style))
    story.append(Paragraph(
        "The Bright Trust Janitorial platform is a comprehensive field-service management and financial auditing system. "
        "It empowers administrators to manage online and phone bookings, control cleaner staff assignments, track job statuses, "
        "issue CRA-compliant invoices, and monitor site analytics.", body_style))
        
    overview_data = [
        [Paragraph("<b>Module</b>", body_style), Paragraph("<b>Primary Function</b>", body_style), Paragraph("<b>Key URL / Location</b>", body_style)],
        [Paragraph("<b>Owner Dashboard</b>", body_style), Paragraph("Active leads table, status filters, search & booking actions", body_style), Paragraph("<code>/dashboard/</code>", body_style)],
        [Paragraph("<b>Cleaning Calendar</b>", body_style), Paragraph("Interactive calendar visualization of active scheduled jobs", body_style), Paragraph("<code>/dashboard/ (Tab 2)</code>", body_style)],
        [Paragraph("<b>Analytics & Traffic</b>", body_style), Paragraph("Monthly revenue breakdown, HST collected, and traffic metrics", body_style), Paragraph("<code>/dashboard/ (Tab 3)</code>", body_style)],
        [Paragraph("<b>Cleaner Staff</b>", body_style), Paragraph("Manage cleaner accounts, 6-digit PIN resets & availability", body_style), Paragraph("<code>/dashboard/cleaners/</code>", body_style)],
        [Paragraph("<b>Pricing Settings</b>", body_style), Paragraph("Base fees, sqft multipliers, HST tax rate & Square link", body_style), Paragraph("<code>/dashboard/settings/</code>", body_style)],
        [Paragraph("<b>CRA Audit Portal</b>", body_style), Paragraph("Immutable financial audit logs and Excel-compatible CSV exports", body_style), Paragraph("<code>/dashboard/audit/</code>", body_style)],
        [Paragraph("<b>Cleaner Portal</b>", body_style), Paragraph("Mobile-optimized job view & photo upload for cleaner staff", body_style), Paragraph("<code>/cleaner/login/</code>", body_style)],
    ]
    t_overview = Table(overview_data, colWidths=[1.4*inch, 3.4*inch, 1.8*inch])
    t_overview.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), LIGHT_BG),
        ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_overview)
    story.append(Spacer(1, 15))

    # ------------------ 2. BOOKING MANAGEMENT ------------------
    story.append(Paragraph("2. Booking Management & Scheduling Workflow", h1_style))
    story.append(Paragraph(
        "The system handles two main sources of bookings: public online requests submitted by clients at <code>/book/</code> "
        "and direct phone/manual bookings created by administrators via the <code>+ Add New Booking</code> button.", body_style))
        
    story.append(Paragraph("Booking Status Lifecycle:", h2_style))
    story.append(Paragraph("• <b>New Request (NEW):</b> Initial quote request submitted online by a prospective customer.", bullet_style))
    story.append(Paragraph("• <b>Contacted (CONTACTED):</b> Staff have reached out to discuss property specifics or customized pricing.", bullet_style))
    story.append(Paragraph("• <b>Scheduled (SCHEDULED):</b> Job is officially booked, calendar slot is locked, 25% deposit email is dispatched, and assigned cleaner is notified.", bullet_style))
    story.append(Paragraph("• <b>Job Done (COMPLETED):</b> Cleaner has completed the service and uploaded 'After' photos. The finalized invoice snapshot is locked.", bullet_style))
    story.append(Paragraph("• <b>Cancelled (CANCELLED):</b> Booking is cancelled and calendar slot is released.", bullet_style))
    
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "<b>Important Rule — Automated Deposit Emails:</b> Whenever a booking transitions to <code>SCHEDULED</code> status, "
        "the platform automatically triggers a dynamic Square Developer API request to generate a 25% downpayment link "
        "and dispatches a confirmation email to the customer.", callout_style))
        
    story.append(Spacer(1, 10))

    # ------------------ 3. CLEANER STAFF MANAGEMENT ------------------
    story.append(Paragraph("3. Cleaner Staff Management Subsystem", h1_style))
    story.append(Paragraph(
        "The platform includes an enterprise multi-cleaner management subsystem located under the <b>Cleaners</b> tab "
        "(<code>/dashboard/cleaners/</code>). Admins can manage staff profiles, set availability statuses, and assign jobs.", body_style))
        
    story.append(Paragraph("Key Security & Operational Features:", h2_style))
    story.append(Paragraph("• <b>2-Factor Phone + 6-Digit PIN Authentication:</b> Cleaners log into <code>/cleaner/login/</code> using their unique phone number and a 6 to 10 digit numeric PIN.", bullet_style))
    story.append(Paragraph("• <b>Secure Hashed PIN Storage:</b> PINs are never stored in plain text; they are encrypted using Django's <code>make_password</code> hash algorithm.", bullet_style))
    story.append(Paragraph("• <b>Daily Availability Statuses:</b> Each cleaner has a daily status (<b>Available</b>, <b>On Leave</b>, <b>Out Sick</b>). Only active & available cleaners appear in job assignment dropdowns.", bullet_style))
    story.append(Paragraph("• <b>Per-Cleaner Schedule Conflict Lock:</b> The system prevents assigning a cleaner to two overlapping scheduled jobs.", bullet_style))
    story.append(Paragraph("• <b>30-Day Mobile Persistent Sessions:</b> Cleaners log in once on their personal phones and stay signed in for 30 days.", bullet_style))
    story.append(Paragraph("• <b>Automated Job Assignment Emails:</b> Assigning a job automatically dispatches a notification email to the cleaner's email address.", bullet_style))
    story.append(Paragraph("• <b>Mobile Privacy Shield:</b> Cleaners see customer address and cleaning instructions, but financial totals, HST calculations, and payment details are strictly hidden.", bullet_style))
    
    story.append(Spacer(1, 15))

    # ------------------ 4. FINANCIAL AUDITING & CRA COMPLIANCE ------------------
    story.append(Paragraph("4. Financial Auditing, Invoicing & CRA Compliance", h1_style))
    story.append(Paragraph(
        "To satisfy Canadian Revenue Agency (CRA) tax compliance and financial reconciliation rules, "
        "the platform enforces strict invoice numbering and immutability constraints:", body_style))
        
    story.append(Paragraph("• <b>Sequential Invoice Numbering:</b> Completed jobs automatically receive a row-locked sequential invoice number formatted as <code>BTJ-YYYY-XXXXXX</code> (e.g. <code>BTJ-2026-000001</code>).", bullet_style))
    story.append(Paragraph("• <b>Immutable Financial Snapshots:</b> Once an invoice is generated, financial fields (subtotal, HST, total price, tax rate used) are locked from further editing.", bullet_style))
    story.append(Paragraph("• <b>Financial Audit Logs:</b> Every status change, price override, payment update, and cleaner assignment is recorded in <code>FinancialAuditLog</code>.", bullet_style))
    story.append(Paragraph("• <b>Excel CSV Exporter:</b> Admins can download a full, UTF-8 BOM formatted financial audit export from <code>/dashboard/audit/export/</code>.", bullet_style))

    story.append(Spacer(1, 15))

    # ------------------ 5. TROUBLESHOOTING & FAQS ------------------
    story.append(Paragraph("5. Administrator Troubleshooting & FAQs", h1_style))
    
    faq_data = [
        [Paragraph("<b>Question / Issue</b>", body_style), Paragraph("<b>Resolution Step</b>", body_style)],
        [Paragraph("How do I reset a cleaner's PIN?", body_style), Paragraph("Go to <b>Cleaners</b> tab -> Click <b>Edit Profile / PIN</b> next to the cleaner -> Type the new 6-digit PIN in the Reset PIN field -> Click <b>Save Changes</b>.", body_style)],
        [Paragraph("What if a cleaner calls in sick?", body_style), Paragraph("Go to <b>Cleaners</b> tab -> Edit cleaner -> Set Availability Status to <b>Out Sick</b> -> Save. The system will prevent assigning them to new jobs.", body_style)],
        [Paragraph("Why am I getting a slot conflict error?", body_style), Paragraph("Check if another active booking exists at the same time or if the assigned cleaner already has a job scheduled during that 4-hour window.", body_style)],
        [Paragraph("How do I change business pricing or tax rates?", body_style), Paragraph("Go to <b>Pricing Settings</b> (<code>/dashboard/settings/</code>) -> Update Base Fee, Sqft Multiplier, or Tax Rate (e.g. <code>0.1300</code> for 13% Ontario HST) -> Save.", body_style)],
    ]
    t_faq = Table(faq_data, colWidths=[2.5*inch, 4.1*inch])
    t_faq.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), LIGHT_BG),
        ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_faq)

    # Build PDF
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Successfully generated PDF Admin Manual at: {filename}")

if __name__ == '__main__':
    output_path = os.path.join(os.path.dirname(__file__), "Bright_Trust_Janitorial_Admin_Manual.pdf")
    create_admin_manual_pdf(output_path)
