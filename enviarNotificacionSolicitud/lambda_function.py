import json
import boto3
import os

ses_client = boto3.client('ses', region_name=os.environ.get('AWS_REGION', 'us-east-2'))

def lambda_handler(event, context):
    print("Iniciando procesamiento de evento SQS...")
    SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'andretitauro@gmail.com')

    for record in event['Records']:
        try:
            message_body = record['body']
            print(f"Mensaje recibido: {message_body}")
            
            notificacion = json.loads(message_body)
            
            destinatario = notificacion.get('correoDestinatario')
            solicitud = notificacion.get('solicitud', {})

            if not destinatario:
                print(f"Error: El mensaje {record['messageId']} no contiene un 'correoDestinatario'. Se omitirá.")
                continue

            estado = solicitud.get('estado', 'desconocido')
            monto = solicitud.get('monto', 0)
            
            subject = f"Actualización de tu solicitud de crédito - CrediYa"
            body_text = (f"Hola,\n\n"
                         f"Te informamos que el estado de tu solicitud de crédito por un monto de ${monto:,.2f} ha sido actualizado a: {estado}.\n\n"
                         f"Gracias por confiar en CrediYa.")
            
            response = ses_client.send_email(
                Destination={
                    'ToAddresses': [
                        destinatario,
                    ],
                },
                Message={
                    'Body': {
                        'Text': {
                            'Charset': 'UTF-8',
                            'Data': body_text,
                        },
                    },
                    'Subject': {
                        'Charset': 'UTF-8',
                        'Data': subject,
                    },
                },
                Source=SENDER_EMAIL,
            )
            
            print(f"Correo enviado a {destinatario}. Message ID: {response['MessageId']}")

        except Exception as e:
            print(f"Error procesando el mensaje: {e}")
    
    return {
        'statusCode': 200,
        'body': json.dumps('Procesamiento completado.')
    }