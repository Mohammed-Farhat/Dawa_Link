import json, smtplib, urllib.request
from email.message import EmailMessage
from dawalink.config import load_settings
for url in ('http://127.0.0.1:58000/api/v1/health','http://127.0.0.1:55173'):
    with urllib.request.urlopen(url) as response:
        print(url, response.status)
settings=load_settings()
body=json.dumps({'email':'client01@demo.dawalink.test','password':settings.demo_accounts_password.get_secret_value()}).encode()
req=urllib.request.Request('http://127.0.0.1:58000/api/v1/auth/login',data=body,headers={'Content-Type':'application/json','Origin':settings.website_url})
with urllib.request.urlopen(req) as response:
    result=json.load(response)
    print('Synthetic client login:',response.status,'token present:',bool(result.get('token')))
message=EmailMessage()
message['From']='probe@evaluation.test'; message['To']='capture@evaluation.test'
message['Subject']='Evaluation isolation smoke'; message.set_content('Synthetic local-only email capture verification.')
with smtplib.SMTP('127.0.0.1',51025) as smtp: smtp.send_message(message)
with urllib.request.urlopen('http://127.0.0.1:58025/api/v1/messages') as response:
    data=json.load(response)
    print('Mail catcher count:',data['total'])
    assert data['total'] >= 1
