from flask import Flask, request, jsonify
from datetime import datetime

# Import the shared workflow state and helper from main.py
from main import workflow_states, advance_workflow

app = Flask(__name__)

@app.route('/api/v1/workflows', methods=['GET'])
def get_all_workflows():
    """
    Returns a list of all current workflows in memory.
    Example response:
      {
        "workflows": [
          {
            "workflow_id": "WF-20250312130000",
            "status": "pending",
            ...
          }
        ]
      }
    """
    workflows_list = []
    for workflow_id, wf in workflow_states.items():
        workflows_list.append({
            'workflow_id': workflow_id,
            'status': wf['status'],
            'created_at': wf['created_at'],
            'invoice_number': wf['invoice_data'].get('invoice_number'),
            'vendor': wf['invoice_data'].get('vendor'),
            'amount': wf['invoice_data'].get('total_amount'),
            'current_step': wf['current_step'],
            'approval_sequence': wf['approval_sequence']
        })
    return jsonify({'workflows': workflows_list})

@app.route('/api/v1/workflow/<workflow_id>', methods=['GET'])
def get_workflow(workflow_id):
    """
    Returns the details of a single workflow by ID.
    Example: GET /api/v1/workflow/WF-20250312130000
    """
    if workflow_id not in workflow_states:
        return jsonify({'error': f'Workflow {workflow_id} not found'}), 404

    wf = workflow_states[workflow_id]
    response = {
        'workflow_id': workflow_id,
        'status': wf['status'],
        'created_at': wf['created_at'],
        'current_step': wf['current_step'],
        'approval_sequence': wf['approval_sequence'],
        'invoice_data': wf['invoice_data'],
        'approvals': wf['approvals'],
        'messages': wf['messages']
    }
    return jsonify(response)

@app.route('/api/v1/approval', methods=['POST'])
def generic_approval():
    """
    Generic endpoint to handle any approver type.
    Expects JSON:
    {
      "workflow_id": "...",
      "approver_type": "financial_approver|department_approver|executive_approver",
      "decision": "approve|reject",
      "reason": "some reason"
    }
    """
    data = request.get_json() or {}
    required = ['workflow_id', 'approver_type', 'decision', 'reason']
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400

    workflow_id = data['workflow_id']
    approver_type = data['approver_type']
    decision = data['decision'].lower()
    reason = data['reason']

    return process_approval_decision(workflow_id, approver_type, decision, reason)

@app.route('/api/v1/financial_approval', methods=['POST'])
def financial_approval():
    """
    Endpoint for financial approvers.
    Expects JSON:
    {
      "workflow_id": "...",
      "decision": "approve|reject",
      "reason": "some reason"
    }
    """
    data = request.get_json() or {}
    for field in ['workflow_id', 'decision', 'reason']:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400

    return process_approval_decision(
        workflow_id=data['workflow_id'],
        approver_type="financial_approver",
        decision=data['decision'].lower(),
        reason=data['reason']
    )

@app.route('/api/v1/department_approval', methods=['POST'])
def department_approval():
    """
    Endpoint for department approvers.
    Expects JSON:
    {
      "workflow_id": "...",
      "decision": "approve|reject",
      "reason": "some reason"
    }
    """
    data = request.get_json() or {}
    for field in ['workflow_id', 'decision', 'reason']:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400

    return process_approval_decision(
        workflow_id=data['workflow_id'],
        approver_type="department_approver",
        decision=data['decision'].lower(),
        reason=data['reason']
    )

@app.route('/api/v1/executive_approval', methods=['POST'])
def executive_approval():
    """
    Endpoint for executive approvers.
    Expects JSON:
    {
      "workflow_id": "...",
      "decision": "approve|reject",
      "reason": "some reason"
    }
    """
    data = request.get_json() or {}
    for field in ['workflow_id', 'decision', 'reason']:
        if field not in data:
            return jsonify({"error": f"Missing required field: {field}"}), 400

    return process_approval_decision(
        workflow_id=data['workflow_id'],
        approver_type="executive_approver",
        decision=data['decision'].lower(),
        reason=data['reason']
    )

def process_approval_decision(workflow_id, approver_type, decision, reason):
    """Helper function to process an approval or rejection for a given workflow."""
    if workflow_id not in workflow_states:
        return jsonify({'error': f'Workflow {workflow_id} not found'}), 404

    workflow = workflow_states[workflow_id]
    if workflow['status'] != 'pending':
        return jsonify({'error': f'Workflow {workflow_id} is already {workflow["status"]}'}), 400

    # Validate the approver is in the sequence
    if approver_type not in workflow['approval_sequence']:
        return jsonify({'error': f'{approver_type} is not part of the approval sequence'}), 400

    # Check if we're at the correct step
    current_step_index = workflow['current_step']
    if current_step_index >= len(workflow['approval_sequence']):
        return jsonify({'error': 'Workflow has already completed all approval steps'}), 400

    expected_approver = workflow['approval_sequence'][current_step_index]
    if approver_type != expected_approver:
        return jsonify({'error': f'Expected approval from {expected_approver}, not {approver_type}'}), 400

    # Validate decision
    if decision not in ['approve', 'reject']:
        return jsonify({'error': 'Decision must be "approve" or "reject"'}), 400

    approved = (decision == 'approve')
    workflow["approvals"][approver_type] = approved
    workflow["messages"].append({
        "role": approver_type,
        "decision": decision,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    })

    # Print confirmation
    print(f"{approver_type.upper()} for workflow {workflow_id}: {decision.upper()}")

    # If rejected, mark workflow as rejected
    if not approved:
        workflow["status"] = "rejected"
    else:
        # Otherwise, move to next step
        workflow["current_step"] += 1
        if workflow["current_step"] >= len(workflow["approval_sequence"]):
            workflow["status"] = "completed"

    # Optionally call advance_workflow if you want extra checks
    advance_workflow(workflow_id)

    return jsonify({
        'status': 'success',
        'workflow_id': workflow_id,
        'workflow_status': workflow["status"],
        'message': f'{approver_type} has {decision}d the invoice.'
    })

if __name__ == '__main__':
    # Run the Flask app (usually you run main.py instead, which imports this)
    app.run(host='0.0.0.0', port=5000)
