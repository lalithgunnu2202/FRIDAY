from dependencies import State,products, short_term_memory
from langgraph.types import interrupt
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# VARIANTS=["size","color"]

def choose_variants(state:State):
    selected_var={}
    memory=short_term_memory.get(state["user_id"])
    prod=products.find_one({"prod_id": memory["prod_id"]},
            {"_id": 0})
    available_variants = prod.get("variants", {})
    for variant_name, options in available_variants.items():
        resp=interrupt(f"choose a {variant_name} from the available {options}")
        selected_var[variant_name]=resp
    return {
        "variants":selected_var
    }

def price_decider(state: State):
    memory = short_term_memory.get(state["user_id"])

    prod_id = memory["prod_id"]

    prod = products.find_one(
        {"prod_id": prod_id},
        {"_id": 0}
    )

    if not prod:
        return {
            "price": None
        }

    if prod.get("variants"):

        selected = state.get("variants", {})
        variant_data = prod.get("variants", {})

        price = prod["price"]

        for variant_name, selected_value in selected.items():

            price_key = f"price_by_{variant_name}"

            if price_key in variant_data:
                price = variant_data[price_key].get(
                    selected_value,
                    price
                )

        return {
            "price": price
        }

    return {
        "price": prod["price"]
    }

def approve(state:State):
    memory=short_term_memory.get(state["user_id"])
    prod_id=memory["prod_id"]
    prod = products.find_one(
        {"prod_id": prod_id},
        {"_id": 0}
    )
    approval=interrupt(
        f"""Do you want to proceed with order of \n Product Name: {prod["title"]} \nPrice: {state['price']} \nTo proceed with order type "yes" in the chat"""
    )
    approved=approval.lower().strip() in ["yes","Yes"]
    return {
        "approval_status":approved,
        "messages":[HumanMessage(content=approval)]
    }
import uuid
def take_address(state:State):
    from dependencies import get_collection
    orders=get_collection("Spes-AI","Orders")
    name = interrupt("Recipient Name?")
    phone = interrupt("Phone Number?")
    address = interrupt("Street Address?")
    city = interrupt("City?")
    state_name = interrupt("State?")
    pincode = interrupt("Pincode?")
    memory=short_term_memory.get(state["user_id"])
    prod_id=memory["prod_id"]
    order_id=f"ORD-{str(uuid.uuid4())[:6].upper()}"
    orders.update_one(
    {"order_id": order_id},
    {"$set": {
        "prod_id":prod_id,
        "recipient_name": name,
        "phone": phone,
        "street_address": address,
        "city": city,
        "state": state_name,
        "pincode": pincode,
        "payment_status":0
    }},
    upsert=True
)
    full_address="\n\n".join([name,phone,address,city,state_name,pincode])
    msg=f"""These are your order details.\nOrder ID: {order_id}\nPrice:{state['price']}\nAddress:{full_address}\nWe have successfully saved your Address for this order.\n\nFinish the payment process by writing "I want to pay" to confirm the order."""
    return {
        "messages":[AIMessage(content=msg)]
    }


def cancel_order(state:State):
    msg=f"Sorry to know you want to cancel the order. Feel free to get served by US."
    return {
        "messages":[AIMessage(content=msg)]
    }

def buy_router(state:State):
    if state["approval_status"]:
        return "take_address"
    else:
        return "cancel_order"


builder = StateGraph(State)

builder.add_node("choose_variants", choose_variants)
builder.add_node("price_decider", price_decider)
builder.add_node("approve", approve)
builder.add_node("take_address", take_address)
builder.add_node("cancel_order", cancel_order)

builder.add_edge(START, "choose_variants")
builder.add_edge("choose_variants", "price_decider")
builder.add_edge("price_decider", "approve")
builder.add_conditional_edges("approve",buy_router,{
    "take_address":"take_address",
    "cancel_order":"cancel_order"
})
builder.add_edge("cancel_order", END)
builder.add_edge("take_address", END)

buy_graph = builder.compile(
    checkpointer=InMemorySaver()
)

# buy_agent.py
from langgraph.types import Command

def buy_response(state: State, resume_value: str = None):
    config = {"configurable": {"thread_id": state["user_id"]}}

    if resume_value is not None:
        result = buy_graph.invoke(Command(resume=resume_value), config=config)
    else:
        result = buy_graph.invoke(state, config=config)

    # Graph paused at an interrupt()
    if "__interrupt__" in result:
        interrupt_prompt = result["__interrupt__"][0].value  # the string you passed to interrupt()
        short_term_memory.update(state["user_id"], buy_flow_active=True)
        return [interrupt_prompt]

    # Graph finished normally
    short_term_memory.update(state["user_id"], buy_flow_active=False)
    messages = result.get("messages", [])
    return [messages[-1].content] if messages else ["Order complete!"]
# def run(query):
#     state={
#             "messages":[],
#             "price":None,
#             "user_id":"abcd",
#             "variants":None
#         }
    