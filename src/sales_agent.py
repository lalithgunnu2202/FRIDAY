from langchain.chat_models import init_chat_model
import os
from dotenv import load_dotenv
from pymongo import MongoClient, TEXT
from pymongo.collection import Collection
from typing_extensions import Annotated, TypedDict
from langgraph.graph.message import add_messages
from datetime import datetime,timezone
from pydantic import BaseModel, Field
from langchain_openrouter import ChatOpenRouter
from enum import Enum
from buy_agent import buy_response
from dependencies import llm, State,products, short_term_memory, Intent,productQuery


# load_dotenv()
# os.environ["OPENROUTER_API_KEY"]=os.getenv("CUSTOM_API_KEY")

# llm = ChatOpenRouter(model="nvidia/nemotron-nano-9b-v2:free")
# print(llm)

# def get_collection(db_name:str,col_name:str)->Collection:
#     client = MongoClient(os.getenv("MONGO_URI"), serverSelectionTimeoutMS=5000)
#     db=client[db_name]
#     collection=db[col_name] #collections are different for different user. i will manage them in my mongodb
#     return collection
    
# class MemoryManager:
#     def __init__(self, collection):
#         self.collection = collection

#     def update(self, user_id, **kwargs):
#         kwargs["updated_at"] = datetime.now(timezone.utc)

#         self.collection.update_one(
#             {"user_id": user_id},
#             {"$set": kwargs},
#             upsert=True
#         )

#     def get(self, user_id):
#         return self.collection.find_one({"user_id": user_id})  #should use **state["memory"] while i am willing to update only particular field

# short_term_memory=MemoryManager(get_collection("Spes-AI","short-term-memory"))
# products=get_collection("Spes-AI","products")

# class State(TypedDict):
#     messages:Annotated[list,add_messages]
#     price:  float | None=None
#     user_id: str|None=None
#     # memory= dict | None=None



structured_llm=llm.with_structured_output(productQuery)

def get_products(result: str, state:State):
    print(result)
    if result.product_id:
        prod=products.find_one(
            {"prod_id": result.product_id},
            {"_id": 0}
        )
        if prod:
            return [prod]
        else:
            return []

    filters = []

    if result.product_type:
        filters.append({
            "$or": [
                {"title": {"$regex": result.product_type, "$options": "i"}},
                {"body_html": {"$regex": result.product_type, "$options": "i"}},
                {"tags": {"$regex": result.product_type, "$options": "i"}},
                {"type": {"$regex": result.product_type, "$options": "i"}},
                {"handle": {"$regex": result.product_type, "$options": "i"}},
            ]
        })

    if result.max_price:
        filters.append({
            "price": {"$lte": result.max_price}
        })

    mongo_filter = {"$and": filters} if filters else {}
    prods=list(products.find(mongo_filter, {"_id": 0}).sort("orders", -1).limit(3))
    if len(prods):
        return prods
    else:
        return []

# print(get_products("show products under 130 rupees"))

def final_prods(result:str,state:State):
    
    # userid="abc12"
    # state={
    #     "messages":[],
    #     "user_id":"abc12"
    # }
    prods=get_products(result,state)
    if len(prods)>1:
        reply=[]
        for prod in prods:
            title=prod["title"]
            desc=prod["body_html"]
            price=prod["price"]
            prod_id=prod["prod_id"]
            msg=f"name: {title} \ndescription: {desc} \nprice: {price} product id: {prod_id} \nUse product id to choose product"
            reply.append(msg)
        reply2="\n\n".join(reply)
        return [reply2]
    elif len(prods)==1:
        prod=prods[0]
        title=prod["title"]
        desc=prod["body_html"]
        price=prod["price"]
        img_link=prod["image_src"]
        prod_id=prod["prod_id"]
        short_term_memory.update(state["user_id"],**{"prod_id":prod_id})
        msg=f"name: {title} \ndescription: {desc} \nprice: {price} product id: {prod_id}"
        return [msg,img_link]
    else:
        return ["No product found"]


def follow_up(query,state:State):
    """this is a follow-up question answering tool. if query looks like a followup question about any product. choose this tool"""
    memory=short_term_memory.get(state["user_id"])
    prod_id=memory["prod_id"]
    short_term_memory.update(state["user_id"],**{"prod_id":prod_id})
    prod=products.find_one(
            {"prod_id": prod_id},
            {"_id": 0}
        )
    if prod:
        prompt = f"""
            Current Product:

            {prod}

            User Question:

            {query}

            Answer only using the product information. and write a ctr message to convert them to buyers. try to answer the users with as short as possible.
            """
        response=llm.invoke(prompt)
        return [response.content]
    else:
        return []

# print(final_prods("show product a5"))
def agent(query, user_id):
    state={
        "message":[],
        "price":None,
        "user_id":user_id,
        "query_result":None,
        "variants": None
    }
    result = structured_llm.invoke(query)
    state["query_result"]=result
    print(result)
    if result.intent==Intent.BROWSE_PRODUCTS:
        return final_prods(result,state)
        
    if result.intent==Intent.BUY_PRODUCT:
        return buy_response(state)
    if result.intent==Intent.FOLLOW_UP_QUESTIONS:
        return follow_up(query,state)
    return ["I am having trouble understanding that. Could you rephrase?"]
    
# print(llm.invoke("what is ai"))
