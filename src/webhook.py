from flask import Flask, request
from dependencies import get_collection
# import asyncio
# from payment_bot import send_confirmation_message


app = Flask(__name__)

import json

@app.route("/razorpay/webhook", methods=["POST"])
def razorpay_webhook():
    orders = get_collection("Spes-AI", "Orders")
    payload = request.json

    # 1. Print the entire JSON payload so you can see its exact structure
    print("--- NEW WEBHOOK RECEIVED ---")
    print(json.dumps(payload, indent=2))

    event = payload.get("event")
    print("EVENT TYPE:", event)

    if event == "payment.captured":
        # 2. Use .get() to safely chain down the dictionary without crashing
        inner_payload = payload.get("payload", {})
        payment_link = inner_payload.get("payment", {})
        entity = payment_link.get("entity", {})
        notes=entity.get("notes",{})
        order_id=notes.get("order_id")

        if not order_id:
            print("WARNING: Could not find order_id in this payload.")
            return "ok", 200

        print("Order ID:", order_id)
        
        # Update database
        orders.update_one(
            {"order_id": order_id},
            {"$set": {"payment_status": 1}}
        )
        print("Database updated successfully.")

    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)