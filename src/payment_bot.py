from telegram import Bot
import os
# from dotenv import load_dotenv

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def send_confirmation_message(
    chat_id: int,
    order_id: str
):
    try:
        bot = Bot(token=BOT_TOKEN)

        msg = f"""
✅ Payment Received

Order ID: {order_id}

Your payment has been verified successfully.

Your order has been confirmed and is now being processed.
"""

        await bot.send_message(
            chat_id=chat_id,
            text=msg
        )

    except Exception as e:
        print(
            f"Failed to send confirmation: {e}"
        )