#!/usr/bin/env python3
"""
Build & deploy: YouTube → Google Drive upload workflow for n8n.
Webhook receives video binary + metadata → uploads to Google Drive → returns link.
"""
import json, urllib.request, urllib.error, uuid

N8N_URL = "https://n8n-n8n.xktssy.easypanel.host"
N8N_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI4ODU1MzcxOC1jOTE3LTQ4NDItYjA1OC1kZWM1MGY3ZTM2NjYiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwiaWF0IjoxNzcyODEzNjA4fQ.MTvOZmWio69tR_UUWxtu0RFMQ6qLcNSto4QPJSxW-XM"

DRIVE_FOLDER_ID = "1iYR7dhUvuWGrShpob9HmJ5H1I32_l5vc"

GOOGLE_DRIVE_CRED = {
    "googleDriveOAuth2Api": {
        "id": "Fvnm9jPEeu3ZhToH",
        "name": "Google Drive account"
    }
}

def uid():
    return str(uuid.uuid4())

def n8n_api(method, path, data=None):
    url = f"{N8N_URL}/api/v1{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "X-N8N-API-KEY": N8N_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    })
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"ERROR {e.code}: {e.read().decode()}")
        raise

# ─── Nodes ───

webhook_node = {
    "parameters": {
        "httpMethod": "POST",
        "path": "youtube-drive-upload",
        "options": {
            "rawBody": True
        },
        "responseMode": "lastNode"
    },
    "type": "n8n-nodes-base.webhook",
    "typeVersion": 2,
    "position": [0, 0],
    "id": uid(),
    "name": "WEBHOOK RECEBER VIDEO",
    "webhookId": uid()
}

# Code node that processes the incoming multipart data
process_node = {
    "parameters": {
        "jsCode": """
// Get the incoming data
const items = $input.all();
const item = items[0];

// Extract metadata from headers or body
const fileName = item.json.body?.fileName || item.json.fileName || 'video.mp4';
const videoTitle = item.json.body?.videoTitle || item.json.videoTitle || fileName;
const videoUrl = item.json.body?.videoUrl || item.json.videoUrl || '';

// Pass through binary data + metadata
return [{
    json: {
        fileName: fileName,
        videoTitle: videoTitle,
        videoUrl: videoUrl,
        uploadTime: new Date().toISOString()
    },
    binary: item.binary
}];
"""
    },
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [220, 0],
    "id": uid(),
    "name": "PROCESSAR DADOS"
}

# Google Drive upload node
drive_upload_node = {
    "parameters": {
        "operation": "upload",
        "name": "={{ $json.fileName }}",
        "folderId": {
            "__rl": True,
            "mode": "id",
            "value": DRIVE_FOLDER_ID
        },
        "inputDataFieldName": "data",
        "options": {}
    },
    "type": "n8n-nodes-base.googleDrive",
    "typeVersion": 3,
    "position": [440, 0],
    "id": uid(),
    "name": "UPLOAD GOOGLE DRIVE",
    "credentials": GOOGLE_DRIVE_CRED
}

# Code node to build response with Drive link
response_node = {
    "parameters": {
        "jsCode": """
const driveFile = $input.all()[0].json;
const fileId = driveFile.id;
const fileName = driveFile.name;
const driveLink = `https://drive.google.com/file/d/${fileId}/view`;

return [{
    json: {
        success: true,
        fileId: fileId,
        fileName: fileName,
        driveLink: driveLink,
        message: `Video "${fileName}" uploaded successfully to Google Drive`
    }
}];
"""
    },
    "type": "n8n-nodes-base.code",
    "typeVersion": 2,
    "position": [660, 0],
    "id": uid(),
    "name": "MONTAR RESPOSTA"
}

nodes = [webhook_node, process_node, drive_upload_node, response_node]

connections = {
    "WEBHOOK RECEBER VIDEO": {
        "main": [[{"node": "PROCESSAR DADOS", "type": "main", "index": 0}]]
    },
    "PROCESSAR DADOS": {
        "main": [[{"node": "UPLOAD GOOGLE DRIVE", "type": "main", "index": 0}]]
    },
    "UPLOAD GOOGLE DRIVE": {
        "main": [[{"node": "MONTAR RESPOSTA", "type": "main", "index": 0}]]
    }
}

workflow_payload = {
    "name": "YouTube → Google Drive Upload",
    "nodes": nodes,
    "connections": connections,
    "settings": {"executionOrder": "v1"}
}

# ─── Deploy ───

def deploy():
    # Check if workflow already exists
    existing = n8n_api("GET", "/workflows?limit=100")
    wf_id = None
    for wf in existing.get("data", []):
        if wf["name"] == "YouTube → Google Drive Upload":
            wf_id = wf["id"]
            break

    if wf_id:
        print(f"Updating existing workflow {wf_id}...")
        # Deactivate first
        try:
            n8n_api("POST", f"/workflows/{wf_id}/deactivate")
        except:
            pass
        # Update
        n8n_api("PUT", f"/workflows/{wf_id}", workflow_payload)
        print(f"Updated workflow {wf_id}")
    else:
        print("Creating new workflow...")
        result = n8n_api("POST", "/workflows", workflow_payload)
        wf_id = result["id"]
        print(f"Created workflow {wf_id}")

    # Activate
    n8n_api("POST", f"/workflows/{wf_id}/activate")
    print(f"Activated workflow {wf_id}")

    webhook_url = f"{N8N_URL}/webhook/youtube-drive-upload"
    print(f"\nWebhook URL: {webhook_url}")
    print(f"Workflow ID: {wf_id}")
    return wf_id, webhook_url

if __name__ == "__main__":
    deploy()
