from flask import Flask, request
from pymongo import MongoClient
from pymongo.collection import Collection
import os
# import asyncio
# from payment_bot import send_confirmation_message


app = Flask(__name__)

import json
def get_collection(db_name:str,col_name:str)->Collection:
    client = MongoClient(os.getenv("MONGO_URI"), serverSelectionTimeoutMS=5000)
    db=client[db_name]
    collection=db[col_name] #collections are different for different user. i will manage them in my mongodb
    return collection


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