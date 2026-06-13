from dependencies import State,products, short_term_memory,get_collection
from langgraph.types import interrupt
import razorpay
from dotenv import load_dotenv
import os
from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.memory import InMemorySaver


def order_details(state: State):
    order_id = interrupt("Please enter your order-id (ORD-XXXXXX) to proceed for the payment")
    short_term_memory.update(state.get("user_id"), buy_flow_active=False, pay_flow_active=False)
    orders_collection = get_collection("Spes-AI", "Orders")
    order = orders_collection.find_one({"order_id": order_id}, {"_id": 0})

    # Bug 3 fix also applied here ↓
    if not order:
        return {"messages": [AIMessage(content="Order not found. Please check your Order ID.")]}

    return {
        "price": order["price"],
        "order_id": order_id,
        "payment_url": order.get("payment_url")  # ← fetch from DB
    }
    
load_dotenv()

client = razorpay.Client(
    auth=(
        os.getenv("TEST_API_KEY"),
        os.getenv("TEST_SECRET")
    )
)


def create_payment_link(
    order_id: str,
    amount: float,
    customer_name: str,
    customer_phone: str
):
    payment_link = client.payment_link.create({
        "amount": int(amount * 100),   # paise
        "currency": "INR",
        "accept_partial": False,
        "reference_id": order_id,
        "description": f"Payment for Order {order_id}",
        "notes":{
            "order_id":order_id
        },
        "customer": {
            "name": customer_name,
            "contact": customer_phone
        },
        "notify": {
            "sms": True,
            "email": False
        },
        "reminder_enable": True
    })

    return {
        "payment_link_id": payment_link["id"],
        "payment_url": payment_link["short_url"]
    }

def payment_agent(state: State):
    order_id = state["order_id"]
    
    # 1. Pause the graph and wait for user input
    msg1 = interrupt(f"""
    Order ID: {order_id}

    Amount: ₹{state['price']}

    Complete payment:
    {state["payment_url"]}

    After payment, your order will be automatically confirmed. Please type "paid" to get details.
    """)

    # 2. Check what the user typed (optional, but good for validation)
    user_input = msg1.lower().strip()
    
    # 3. Query the database CORRECTLY using a dictionary
    orders = get_collection("Spes-AI", "Orders")
    order = orders.find_one({"order_id": order_id})

    # 4. Safely check if the order exists AND the payment status is updated
    if order and order.get("payment_status") == 1:
        msg2 = f"""
        Order ID: {order_id}\n\nAmount: ₹{state['price']}\n\nPayment is successful. We will contact you as we dispatch the order.\n\nHave a great shopping!
        """
        return {"messages": [AIMessage(content=msg2)]}
        
    else:
        msg3 = f"""
        Order ID: {order_id}\n\nAmount: ₹{state['price']}\n\nIt seems like your payment hasn't been received yet or failed. You can try again using the same link.
        """
        return {"messages": [AIMessage(content=msg3)]}

    # orders=get_collection("Spes-AI","Orders")
    # orders.update_one(
    #     {"order_id": order_id},
    #     {"$set": {"chat_id": state["chat_id"]}}
    # )

def init_state(state: State):
    return {"user_id": state.get("user_id")}
pay_build=StateGraph(State)

pay_build.add_node("init_state", init_state)
pay_build.add_node("order_details", order_details)
pay_build.add_node("payment_agent", payment_agent)

pay_build.add_edge(START, "init_state")
pay_build.add_edge("init_state", "order_details")
pay_build.add_edge("order_details","payment_agent")
pay_build.add_edge("payment_agent",END)
pay_graph=pay_build.compile(checkpointer=InMemorySaver())

from langgraph.types import Command

def pay_response(state: State, resume_value: str = None):
    config = {"configurable": {"thread_id": state.get("user_id")}}
    user_id = state.get("user_id")

    try:
        if resume_value is not None:
            result = pay_graph.invoke(Command(resume=resume_value), config=config)
        else:
            result = pay_graph.invoke(state, config=config)
    except Exception as e:
        short_term_memory.update(user_id, pay_flow_active=False)
        result = pay_graph.invoke(state, config=config)

    if "__interrupt__" in result:
        short_term_memory.update(user_id, pay_flow_active=True)  # still in progress
        return [result["__interrupt__"][0].value]

    # Graph reached END — clean up
    short_term_memory.update(user_id, buy_flow_active=False, pay_flow_active=False)
    messages = result.get("messages", [])
    return [messages[-1].content] if messages else ["Payment completed!"]

