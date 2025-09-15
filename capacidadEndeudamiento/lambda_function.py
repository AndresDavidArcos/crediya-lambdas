import json
import boto3
import os
from decimal import Decimal, getcontext

getcontext().prec = 28

ses_client = boto3.client('ses')
sqs_client = boto3.client('sqs')

def calcular_cuota_mensual(monto_str, tasa_anual_str, plazo_meses):
    """Calcula la cuota mensual fija usando la fórmula de amortización francesa."""
    try:
        monto = Decimal(str(monto_str))
        tasa_anual = Decimal(str(tasa_anual_str))
        plazo = Decimal(str(plazo_meses))

        if tasa_anual <= 0 or plazo <= 0 or monto <= 0:
            return Decimal('0.0')

        tasa_mensual = tasa_anual / Decimal('12') / Decimal('100')
        
        if tasa_mensual == 0:
            return (monto / plazo).quantize(Decimal('0.01'))
            
        cuota = (monto * tasa_mensual) / (1 - (1 + tasa_mensual)**-plazo)
        return cuota.quantize(Decimal('0.01'))
        
    except Exception as e:
        print(f"Error calculando cuota mensual: {e}")
        return Decimal('0.0')

def generar_plan_pagos(monto_str, tasa_anual_str, plazo_meses):
    """Genera una tabla de amortización completa en formato de texto plano."""
    cuota = calcular_cuota_mensual(monto_str, tasa_anual_str, plazo_meses)
    saldo_pendiente = Decimal(str(monto_str))
    tasa_mensual = Decimal(str(tasa_anual_str)) / Decimal('12') / Decimal('100')
    plan = []

    plan.append("Plan de Pagos Detallado:\n")
    plan.append(f"{'Mes':<5}| {'Cuota Mensual':<15}| {'Intereses':<12}| {'Abono a Capital':<18}| {'Saldo Pendiente':<18}\n")
    plan.append("-" * 72 + "\n")

    for mes in range(1, int(plazo_meses) + 1):
        intereses = (saldo_pendiente * tasa_mensual).quantize(Decimal('0.01'))
        abono_capital = (cuota - intereses).quantize(Decimal('0.01'))
        
        if mes == int(plazo_meses):
            ajuste = saldo_pendiente - abono_capital
            cuota += ajuste
            abono_capital += ajuste
        
        saldo_pendiente -= abono_capital

        plan.append(
            f"{mes:<5}| ${cuota:14,.2f}| ${intereses:11,.2f}| ${abono_capital:17,.2f}| ${saldo_pendiente:17,.2f}\n"
        )
    return "".join(plan)

def lambda_handler(event, context):
    decision_queue_url = os.environ.get('DECISION_QUEUE_URL')
    sender_email = os.environ.get('SENDER_EMAIL')

    for record in event['Records']:
        payload = {}
        try:
            payload = json.loads(record['body'])
            print("--- PAYLOAD COMPLETO RECIBIDO ---")
            print(json.dumps(payload, indent=2))

            solicitud_actual = payload.get('solicitudActual', {})
            usuario = payload.get('usuario', {})
            tipo_prestamo = payload.get('tipoPrestamo', {})
            prestamos_aprobados = payload.get('prestamosAprobados', [])

            solicitud_id = solicitud_actual.get('id')
            salario_base = Decimal(usuario.get('salarioBase', 0))
            correo_cliente = usuario.get('correoElectronico')

            capacidad_maxima = salario_base * Decimal('0.35')

            deuda_actual = Decimal('0.0')
            for prestamo in prestamos_aprobados:
                deuda_actual += calcular_cuota_mensual(
                    prestamo.get('monto'),
                    prestamo.get('tasaInteres'),
                    prestamo.get('plazoEnMeses')
                )

            capacidad_disponible = capacidad_maxima - deuda_actual
            
            tasa_interes_nuevo_prestamo = tipo_prestamo.get('tasaInteres')
            cuota_nueva = calcular_cuota_mensual(
                solicitud_actual.get('monto'), 
                tasa_interes_nuevo_prestamo, 
                solicitud_actual.get('plazoEnMeses')
            )

            #Toma de desicion
            nuevo_estado = "Rechazada"
            if cuota_nueva <= capacidad_disponible:
                nuevo_estado = "Aprobada"
                if Decimal(solicitud_actual.get('monto')) > (salario_base * 5):
                    nuevo_estado = "Revision manual"

            decision_payload = {
                'solicitudId': solicitud_id,
                'nuevoEstado': nuevo_estado
            }
            
            sqs_client.send_message(
                QueueUrl=decision_queue_url,
                MessageBody=json.dumps(decision_payload)
            )
            print(f"Comando para actualizar estado de solicitud {solicitud_id} a '{nuevo_estado}' enviado a la cola.")
           

            #Enviar notificación por correo con SES
            monto_solicitado = solicitud_actual.get('monto', 0)
            plazo_solicitado = solicitud_actual.get('plazoEnMeses', 0)
            tipo_prestamo_nombre = tipo_prestamo.get('nombre', 'No especificado')          
            subject = f"Decisión sobre tu solicitud de crédito No. {solicitud_id} - CrediYa"
            body = (
                f"Hola {usuario.get('nombres')},\n\n"
                f"Te informamos sobre tu solicitud de crédito:\n\n"
                f"  - Tipo de Préstamo: {tipo_prestamo_nombre}\n"
                f"  - Monto Solicitado: ${Decimal(monto_solicitado):,.2f}\n"
                f"  - Plazo: {plazo_solicitado} meses\n\n"
                f"El resultado del análisis automático es: {nuevo_estado}.\n\n"
            )
            
            if nuevo_estado == "Aprobada":
                plan_de_pagos = generar_plan_pagos(
                    solicitud_actual.get('monto'),
                    tasa_interes_nuevo_prestamo,
                    solicitud_actual.get('plazoEnMeses')
                )
                body += f"Tu cuota mensual estimada es de: ${cuota_nueva:,.2f}\n\n"
                body += plan_de_pagos
            
            ses_client.send_email(
                Source=sender_email,
                Destination={'ToAddresses': [correo_cliente]},
                Message={'Subject': {'Data': subject}, 'Body': {'Text': {'Data': body}}}
            )
            print(f"Correo de decisión enviado a {correo_cliente}.")

        except Exception as e:
            print(f"Error procesando la solicitud {payload.get('solicitudActual', {}).get('id', 'desconocido')}: {e}")

    return {'statusCode': 200}