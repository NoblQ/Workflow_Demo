
import os
import re
import imaplib
import email
import json
import pdfplumber
import openai
from datetime import datetime
from typing import Dict, Any, List, Optional

IMAP_HOST = "imap.zoho.com"
EMAIL_USER = "noblq.mail@zohomail.com"
EMAIL_PASS = "RFXCBw98bE6k"
SEARCH_CRITERIA = '(SUBJECT "Invoice")'

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY"
)
openai.api_key = OPENAI_API_KEY
workflow_states = {}


def fetch_emails_with_attachments():
    """Fetch emails with invoice attachments and download them"""
    attachment_dir = "attachments"
    os.makedirs(attachment_dir, exist_ok=True)
    downloaded_files = []

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, 993)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("INBOX")

        typ, msg_nums = mail.search(None, SEARCH_CRITERIA)
        if typ != "OK":
            print("Error searching Inbox.")
            return downloaded_files

        for num in msg_nums[0].split():
            typ, msg_data = mail.fetch(num, "(RFC822)")
            if typ != "OK":
                print(f"Error fetching mail id {num.decode()}.")
                continue

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            sender = msg.get('From', 'Unknown')
            subject = msg.get('Subject', 'No Subject')

            print(f"Processing email from {sender}: {subject}")

            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue

                content_disp = part.get("Content-Disposition")
                if content_disp and "attachment" in content_disp.lower():
                    filename = part.get_filename()
                    if not filename:
                        filename = f"attachment_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"

                    if part.get_content_type() in [
                            "application/pdf", "application/octet-stream"
                    ]:
                        filepath = os.path.join(attachment_dir, filename)
                        counter = 1
                        base_filename, ext = os.path.splitext(filename)

                        while os.path.exists(filepath):
                            filepath = os.path.join(
                                attachment_dir,
                                f"{base_filename}_{counter}{ext}")
                            counter += 1

                        with open(filepath, "wb") as f:
                            f.write(part.get_payload(decode=True))

                        print(f"Downloaded attachment: {filepath}")
                        downloaded_files.append({
                            'path': filepath,
                            'sender': sender,
                            'subject': subject,
                            'date': msg.get('Date')
                        })

            # Mark email as seen
            mail.store(num, '+FLAGS', '\\Seen')

        mail.close()
        mail.logout()

    except Exception as e:
        print(f"Error during email retrieval: {e}")

    return downloaded_files


def upload_documents(file_paths: List[str]) -> List[Dict[str, Any]]:
    """
    Process manually uploaded documents
    In a real application, this would be linked to a file upload UI
    """
    uploaded_files = []

    for path in file_paths:
        if os.path.exists(path) and path.lower().endswith('.pdf'):
            uploaded_files.append({
                'path':
                path,
                'sender':
                'Manual Upload',
                'subject':
                os.path.basename(path),
                'date':
                datetime.now().strftime("%a, %d %b %Y %H:%M:%S")
            })
        else:
            print(f"Invalid file: {path}")

    return uploaded_files


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text content from a PDF file"""
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text += page_text + "\n"
    except Exception as e:
        print(f"Error reading {pdf_path}: {e}")

    return text.strip()


def extract_invoice_data(pdf_text: str) -> Dict[str, Any]:
    """
    Extract structured invoice data from text using OpenAI
    Returns a dictionary with invoice details
    """
    system_prompt = (
        "You are a helpful assistant that extracts structured data from purchase orders. "
        "Return only valid JSON with the following keys: invoice_number, date, vendor, total_amount, line_items. "
        "Line_items should be an array of objects with keys: description, quantity, unit_price, total. "
        "If a field is missing, use null.")

    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{
                "role": "system",
                "content": system_prompt
            }, {
                "role":
                "user",
                "content":
                f"Extract structured data from this purchase order:\n\n{pdf_text}"
            }],
            temperature=0.0,
            max_tokens=800)
        content = response.choices[0].message.content
        structured_data = json.loads(content)
        return structured_data
    except Exception as e:
        print(f"Error extracting invoice data: {e}")
        return {
            "invoice_number": None,
            "date": None,
            "vendor": None,
            "total_amount": None,
            "line_items": []
        }


def create_approval_workflow(invoice_data: Dict[str, Any]) -> str:
    """
    Create a new approval workflow for an invoice
    Returns the workflow ID
    """
    workflow_id = f"WF-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Create approval sequence with all three approvers for every invoice
    approval_sequence = [
        "financial_approver",
        "department_approver", 
        "executive_approver"
    ]

    workflow_states[workflow_id] = {
        "invoice_data": invoice_data,
        "approval_sequence": approval_sequence,
        "current_step": 0,
        "approvals": {},
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "messages": []
    }

    print(
        f"Created workflow {workflow_id} with {len(approval_sequence)} approval steps"
    )
    return workflow_id


def advance_workflow(workflow_id: str) -> Dict[str, Any]:
    """
    Advance the workflow to the next approval step
    Returns the updated workflow state
    """
    import time

    if workflow_id not in workflow_states:
        raise ValueError(f"Workflow {workflow_id} not found")

    workflow = workflow_states[workflow_id]

    # If all approvals are complete, mark the workflow as completed
    if workflow["current_step"] >= len(workflow["approval_sequence"]):
        workflow["status"] = "completed"
        return workflow

    # Get the current approver
    current_approver = workflow["approval_sequence"][workflow["current_step"]]

    # If this step is already approved, move to the next step
    if current_approver in workflow["approvals"] and workflow["approvals"][
            current_approver]:
        print(f"Waiting for next approval step...")
        time.sleep(10)  # 10 second delay between approval steps
        
        workflow["current_step"] += 1

        # If we've reached the end, mark as completed
        if workflow["current_step"] >= len(workflow["approval_sequence"]):
            workflow["status"] = "completed"

        return workflow

    # Otherwise, wait for approval
    print(
        f"Workflow {workflow_id} waiting for approval from {current_approver}")

    return workflow


def financial_approver(workflow_id: str) -> Dict[str, Any]:
    """
    Financial approver function
    In a real app, this would be an API endpoint or interactive UI
    """
    if workflow_id not in workflow_states:
        raise ValueError(f"Workflow {workflow_id} not found")

    workflow = workflow_states[workflow_id]
    invoice = workflow["invoice_data"]

    print(
        f"Financial approver reviewing invoice {invoice.get('invoice_number', 'Unknown')}"
    )
    print(f"Vendor: {invoice.get('vendor', 'Unknown')}")
    print(f"Amount: {invoice.get('total_amount', 'Unknown')}")

    decision = "approve"  # or "reject"
    reason = "Invoice amount is within budget and payment terms are acceptable."

    # Record the approval decision
    workflow["approvals"]["financial_approver"] = (decision == "approve")
    workflow["messages"].append({
        "role": "financial_approver",
        "decision": decision,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    })

    if decision == "approve":
        print("Financial approval: APPROVED")
    else:
        print("Financial approval: REJECTED")
        workflow["status"] = "rejected"

    return workflow


def department_approver(workflow_id: str) -> Dict[str, Any]:
    """
    Department approver function
    Verifies that goods/services were received as described
    """
    if workflow_id not in workflow_states:
        raise ValueError(f"Workflow {workflow_id} not found")

    workflow = workflow_states[workflow_id]
    invoice = workflow["invoice_data"]

    print(
        f"Department approver reviewing invoice {invoice.get('invoice_number', 'Unknown')}"
    )
    print(f"Vendor: {invoice.get('vendor', 'Unknown')}")

    line_items = invoice.get('line_items', [])
    for i, item in enumerate(line_items):
        print(
            f"Item {i+1}: {item.get('description', 'Unknown')} - Qty: {item.get('quantity', 'Unknown')}"
        )

    decision = "approve"  # or "reject"
    reason = "All goods/services listed were received and meet quality standards."

    workflow["approvals"]["department_approver"] = (decision == "approve")
    workflow["messages"].append({
        "role": "department_approver",
        "decision": decision,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    })

    if decision == "approve":
        print("Department approval: APPROVED")
    else:
        print("Department approval: REJECTED")
        workflow["status"] = "rejected"

    return workflow


def executive_approver(workflow_id: str) -> Dict[str, Any]:
    """
    Executive approver function for high-value invoices
    """
    if workflow_id not in workflow_states:
        raise ValueError(f"Workflow {workflow_id} not found")

    workflow = workflow_states[workflow_id]
    invoice = workflow["invoice_data"]

    print(
        f"Executive approver reviewing high-value invoice {invoice.get('invoice_number', 'Unknown')}"
    )
    print(f"Vendor: {invoice.get('vendor', 'Unknown')}")
    print(f"Amount: {invoice.get('total_amount', 'Unknown')}")

    decision = "approve"  # or "reject"
    reason = "Strategic vendor relationship and expenditure is justified."

    workflow["approvals"]["executive_approver"] = (decision == "approve")
    workflow["messages"].append({
        "role": "executive_approver",
        "decision": decision,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    })

    if decision == "approve":
        print("Executive approval: APPROVED")
    else:
        print("Executive approval: REJECTED")
        workflow["status"] = "rejected"

    return workflow


def process_ui_approval(workflow_id: str, approver_type: str, approved: bool,
                        reason: str) -> Dict[str, Any]:
    """
    Process an approval decision made through the UI
    """
    if workflow_id not in workflow_states:
        raise ValueError(f"Workflow {workflow_id} not found")

    workflow = workflow_states[workflow_id]

    current_step = workflow["current_step"]
    if current_step >= len(workflow["approval_sequence"]):
        raise ValueError("Workflow has already completed all approval steps")

    expected_approver = workflow["approval_sequence"][current_step]
    if approver_type != expected_approver:
        raise ValueError(
            f"Expected approval from {expected_approver}, but got {approver_type}"
        )

    workflow["approvals"][approver_type] = approved
    workflow["messages"].append({
        "role": approver_type,
        "decision": "approve" if approved else "reject",
        "reason": reason,
        "method": "ui",
        "timestamp": datetime.now().isoformat()
    })

    if not approved:
        workflow["status"] = "rejected"
    else:
        workflow["current_step"] += 1
        if workflow["current_step"] >= len(workflow["approval_sequence"]):
            workflow["status"] = "completed"

    print(
        f"UI Approval processed for {approver_type}: {'APPROVED' if approved else 'REJECTED'}"
    )
    return workflow


def process_email_approval(
        email_content: str,
        workflow_id: str = None) -> Optional[Dict[str, Any]]:
    """
    Process an approval decision made through email
    In a real app, this would parse incoming emails
    """
    if not workflow_id:

        match = re.search(r'\[(WF-\d+)\]', email_content)
        if match:
            workflow_id = match.group(1)
        else:
            print("Could not find workflow ID in email")
            return None

    if workflow_id not in workflow_states:
        print(f"Workflow {workflow_id} not found")
        return None

    workflow = workflow_states[workflow_id]

    approved = ("approve" in email_content.lower()
                or "yes" in email_content.lower())
    rejected = ("reject" in email_content.lower()
                or "no" in email_content.lower())

    if not (approved or rejected):
        print("Email does not contain clear approval or rejection")
        return None

    current_step = workflow["current_step"]
    if current_step >= len(workflow["approval_sequence"]):
        print("Workflow has already completed all approval steps")
        return None

    approver_type = workflow["approval_sequence"][current_step]

    reason_match = re.search(r'reason:\s*(.+)', email_content, re.IGNORECASE)
    reason = reason_match.group(1) if reason_match else "No reason provided"

    # Record the approval decision
    workflow["approvals"][approver_type] = approved
    workflow["messages"].append({
        "role": approver_type,
        "decision": "approve" if approved else "reject",
        "reason": reason,
        "method": "email",
        "timestamp": datetime.now().isoformat()
    })

    if not approved:
        workflow["status"] = "rejected"
    else:
        # Move to the next step
        workflow["current_step"] += 1
        if workflow["current_step"] >= len(workflow["approval_sequence"]):
            workflow["status"] = "completed"

    print(
        f"Email Approval processed for {approver_type}: {'APPROVED' if approved else 'REJECTED'}"
    )
    return workflow


def process_invoice(document_path: str,
                    upload_method: str = "email",
                    auto_approve: bool = False):
    """
    Process a single invoice document through the entire workflow
    If auto_approve is False, will wait for external approval via API
    """
    print(f"\n{'='*50}")
    print(f"Processing invoice: {document_path}")
    print(f"{'='*50}")

    # Step 1: Extract text from PDF
    pdf_text = extract_text_from_pdf(document_path)
    if not pdf_text:
        print(f"Could not extract text from {document_path}")
        return

    print(f"Extracted {len(pdf_text)} characters from document")

    # Step 2: Parse invoice data
    invoice_data = extract_invoice_data(pdf_text)
    if not invoice_data:
        print("Failed to parse invoice data")
        return

    print(f"Parsed invoice #{invoice_data.get('invoice_number', 'Unknown')}")
    print(f"Vendor: {invoice_data.get('vendor', 'Unknown')}")
    print(f"Amount: {invoice_data.get('total_amount', 'Unknown')}")

    # Step 3: Create approval workflow
    workflow_id = create_approval_workflow(invoice_data)

    # Step 4: Process approvals (only if auto_approve is True)
    if auto_approve:
        current_workflow = workflow_states[workflow_id]

        while current_workflow["status"] == "pending":
            # Get current approver
            current_step = current_workflow["current_step"]
            if current_step >= len(current_workflow["approval_sequence"]):
                current_workflow["status"] = "completed"
                break

            current_approver = current_workflow["approval_sequence"][
                current_step]
            print(
                f"\nStep {current_step + 1}: Auto-processing {current_approver} approval"
            )

            # Process approval based on approver type
            if current_approver == "financial_approver":
                current_workflow = financial_approver(workflow_id)
            elif current_approver == "department_approver":
                current_workflow = department_approver(workflow_id)
            elif current_approver == "executive_approver":
                current_workflow = executive_approver(workflow_id)
            else:
                print(f"Unknown approver type: {current_approver}")
                break

            if current_workflow["status"] == "rejected":
                print(f"\nWorkflow {workflow_id} was REJECTED")
                break

            current_workflow = advance_workflow(workflow_id)

        if current_workflow["status"] == "completed":
            print(f"\nWorkflow {workflow_id} COMPLETED successfully")
            print("All approvals received!")
        elif current_workflow["status"] == "rejected":
            print(f"\nWorkflow {workflow_id} was REJECTED")
            # Find which approver rejected
            for approver, approved in current_workflow["approvals"].items():
                if not approved:
                    print(f"Rejected by: {approver}")
                    break
        else:
            print(f"\nWorkflow {workflow_id} is still PENDING")

        # Summary of approvals
        print("\nApproval Summary:")
        for msg in current_workflow["messages"]:
            print(
                f"- {msg['role']} {msg['decision'].upper()} at {msg['timestamp']}"
            )
            print(f"  Reason: {msg['reason']}")
    else:
        # Just notify that approval is pending via API
        print(f"\nWorkflow {workflow_id} is awaiting approval via API")
        print(
            f"Current approval step: {workflow_states[workflow_id]['current_step'] + 1} of {len(workflow_states[workflow_id]['approval_sequence'])}"
        )
        print(
            f"Waiting for: {workflow_states[workflow_id]['approval_sequence'][workflow_states[workflow_id]['current_step']]}"
        )
        print(f"Use API endpoint to approve: POST /api/v1/approval")
        print(f"Example payload:")
        print(f'''{{
  "workflow_id": "{workflow_id}",
  "approver_type": "{workflow_states[workflow_id]['approval_sequence'][workflow_states[workflow_id]['current_step']]}",
  "decision": "approve",
  "reason": "Invoice verified and approved."
}}''')

    return workflow_id


def simulate_email_approval(workflow_id: str, approve: bool = True):
    """Simulate receiving an email approval for testing"""

    if workflow_id not in workflow_states:
        print(f"Workflow {workflow_id} not found")
        return

    workflow = workflow_states[workflow_id]
    current_step = workflow["current_step"]

    if current_step >= len(workflow["approval_sequence"]):
        print("No pending approval steps")
        return

    approver = workflow["approval_sequence"][current_step]
    action = "approve" if approve else "reject"

    email_content = f"""
    Subject: RE: [Invoice Approval] [{workflow_id}]
    
    I {action} this invoice.
    
    Reason: Reviewed and found {'acceptable' if approve else 'unacceptable'}.
    
    Best regards,
    Test User
    """

    result = process_email_approval(email_content, workflow_id)
    if result:
        print(f"Email approval simulation processed for {approver}")
        return result
    else:
        print("Email approval simulation failed")
        return None

def simulate_ui_approval(workflow_id: str,
                         approve: bool = True,
                         reason: str = "Reviewed and approved"):
    """Simulate UI approval for testing"""

    if workflow_id not in workflow_states:
        print(f"Workflow {workflow_id} not found")
        return

    workflow = workflow_states[workflow_id]
    current_step = workflow["current_step"]

    if current_step >= len(workflow["approval_sequence"]):
        print("No pending approval steps")
        return

    approver = workflow["approval_sequence"][current_step]

    result = process_ui_approval(workflow_id, approver, approve, reason)
    print(f"UI approval simulation processed for {approver}")
    return result


def main():
    """Main function to demonstrate the invoice processing workflow"""
    print("=== Invoice Processing Application ===\n")

    print("Checking emails for invoice attachments...")
    email_documents = fetch_emails_with_attachments()

    if email_documents:
        print(f"Found {len(email_documents)} documents in emails")
        for doc in email_documents:
            process_invoice(doc['path'], "email", auto_approve=False)
    else:
        print("No new invoice attachments found in emails")

    # Option 2: Process files in the attachments directory
    print("\nChecking attachments directory for invoice files...")
    attachment_dir = "attachments"

    if os.path.exists(attachment_dir):
        files = [
            os.path.join(attachment_dir, f) for f in os.listdir(attachment_dir)
            if f.lower().endswith('.pdf')
        ]
        if files:
            print(f"Found {len(files)} PDF files in attachments directory")
            
            print("\n=== Processing PDFs with Auto-Approval ===")
            # Limit to first 3 files to avoid excessive processing
            files_to_process = files[:3]
            print(f"Processing the first {len(files_to_process)} of {len(files)} PDF files...")
            
            for pdf_file in files_to_process:
                print(f"\nProcessing file with auto-approval: {pdf_file}")
                workflow_id = process_invoice(pdf_file, "upload", auto_approve=True)
                
                # Print summary of completed workflow
                if workflow_id and workflow_id in workflow_states:
                    workflow = workflow_states[workflow_id]
                    print(f"\nWorkflow {workflow_id} for {os.path.basename(pdf_file)}:")
                    print(f"Status: {workflow['status']}")
                    print("Approvals:")
                    for approver, approved in workflow['approvals'].items():
                        print(f"- {approver}: {'APPROVED' if approved else 'REJECTED'}")
            
            # Show how many files were skipped
            if len(files) > len(files_to_process):
                print(f"\nSkipped processing {len(files) - len(files_to_process)} additional PDF files.")
                print("To process more files, modify the limit in the code.")
        else:
            print("No PDF files found in attachments directory")

    print("\n=== Starting API Server ===")
    
    print("Invoice approval API is now available at http://0.0.0.0:5000")
    print("Use the following endpoints:")
    print("- GET /api/v1/workflows - List all workflows")
    print("- GET /api/v1/workflow/<workflow_id> - Get workflow details")
    print("- POST /api/v1/approval - Process an approval")

    try:
        import api
        api.app.run(host='0.0.0.0', port=5000)
    except ImportError:
        print(
            "API module not found. Please run the system with 'flask' installed."
        )
        print("You can install it with: pip install flask")


if __name__ == "__main__":
    main()
