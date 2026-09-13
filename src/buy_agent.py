from dependencies import State,products, short_term_memory, no_trace
from langgraph.types import interrupt
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage, AIMessage
from payment_agent import create_payment_link
from langsmith import traceable

@traceable(name="Process Order Approval")
def approve(state: State):
    user_id = state.get("user_id")
    memory = short_term_memory.get(user_id)

    if not memory or not memory.get("prod_id"):
        return {"messages": [AIMessage(content="Session expired. Please select a product again.")],
                "user_id": user_id, "approval_status": False}

    prod = products.find_one({"prod_id": memory["prod_id"]}, {"_id": 0})
    if not prod:
        return {"messages": [AIMessage(content="Product no longer available.")],
                "user_id": user_id, "approval_status": False}

    price = prod.get("price")

    approval = interrupt(
        f"""Do you want to proceed with order of \n Product Name: {prod.get("title", "Product")} \nPrice: {price} \nTo proceed with order type "yes" in the chat"""
    )
    approved = approval.lower().strip() in ["yes", "Yes"]
    return {
        "price": price,
        "approval_status": approved,
        "messages": [HumanMessage(content=approval)]
    }
import uuid

@traceable(name="collecting address")
def take_address(state:State):
    from dependencies import get_collection
    orders=get_collection("Spes-AI","Orders")     
    address=interrupt("Enter the address in this format\nName: John Doe\n"
        "Phone: 9876543210\n"
        "Address: 123 Main St\n"
        "City: Mumbai\n"
        "State: Maharashtra\n"
        "Pincode: 400001")
    memory=short_term_memory.get(state.get("user_id"))
    # short_term_memory.update(state.get("user_id"), buy_flow_active=False, pay_flow_active=False)
    prod_id=memory["prod_id"]
    order_id=f"ORD{str(uuid.uuid4())[:4].upper()}"
    payment = create_payment_link(
        order_id=order_id,
        amount=state["price"],
        customer_name="Lark-AI",
        customer_phone=None
    )
    orders.update_one(
        {"order_id": order_id},
        {"$set": {
            "address":address,
            "price":state["price"],
            "prod_id":prod_id,
            "payment_status":0,
            "payment_link_id": payment["payment_link_id"],
            "payment_url": payment["payment_url"]
        }},
        upsert=True
    )
    short_term_memory.update(state.get("user_id"),**{"price":state["price"]})
    msg=f"""These are your order details.\nOrder ID: {order_id}\nPrice:{state['price']}\nAddress:{address}\nWe have successfully saved your Address for this order.\n\nFinish the payment process by writing "I want to pay" to confirm the order."""
    return {
        "messages":[AIMessage(content=msg)],
        "payment_url":payment["payment_url"]
    }

@traceable(name="Cancelling Order")
def cancel_order(state:State):
    msg=f"Sorry to know you want to cancel the order. Feel free to get served by US."
    short_term_memory.update(state["user_id"], buy_flow_active=False)
    return {
        "messages":[AIMessage(content=msg)]
    }

@no_trace
def cancel_router(state: State):
    if state["cancel_status"]:
        return "cancel_order"

    return "continue"

@no_trace
def init_state(state: State):
    user_id = state.get("user_id")

    short_term_memory.update(
        user_id,
        variants={}
    )

    return {
        "user_id": user_id,
        "cancel_status": False
    }


builder = StateGraph(State)

# Nodes
builder.add_node("init_state", init_state)
builder.add_node("approve", approve)
builder.add_node("take_address", take_address)
builder.add_node("cancel_order", cancel_order)


# START
builder.add_edge(START, "init_state")


# init_state → cancellation check
builder.add_conditional_edges(
    "init_state",
    cancel_router,
    {
        "continue": "approve",
        "cancel_order": "cancel_order"
    }
)


# approve → either normal flow or cancellation
def buy_router(state: State):
    if state.get("approval_status"):
        return "take_address"

    return "cancel_order"


builder.add_conditional_edges(
    "approve",
    buy_router,
    {
        "take_address": "take_address",
        "cancel_order": "cancel_order"
    }
)


# take_address → cancellation check
builder.add_conditional_edges(
    "take_address",
    cancel_router,
    {
        "continue": END,
        "cancel_order": "cancel_order"
    }
)


# Cancellation terminates the graph
builder.add_edge("cancel_order", END)


buy_graph = builder.compile(
    checkpointer=InMemorySaver()
)

# buy_agent.py
from langgraph.types import Command

@traceable(name="Buy Agent")
def buy_response(state: State, resume_value: str = None):
    config = {"configurable": {"thread_id": state.get("user_id")}}
    user_id = state.get("user_id")

    try:
        if resume_value is not None:
            result = buy_graph.invoke(Command(resume=resume_value), config=config)
        else:
            result = buy_graph.invoke(state, config=config)
    except Exception as e:
        import traceback
        traceback.print_exc()
        short_term_memory.update(user_id, buy_flow_active=False)
        return [f"Sorry, an error occurred processing your request: {str(e)}"]

    if "__interrupt__" in result:
        short_term_memory.update(user_id, buy_flow_active=True)  # still in progress
        return [result["__interrupt__"][0].value]

    # Graph reached END — clean up
    short_term_memory.update(user_id, buy_flow_active=False, pay_flow_active=False)
    messages = result.get("messages", [])
    return [messages[-1].content] if messages else ["Order complete!"]
# def run(query):
#     state={
#             "messages":[],
#             "price":None,
#             "user_id":"abcd",
#             "variants":None
#         }
    