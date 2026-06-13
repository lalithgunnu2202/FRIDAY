from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
import os
from dotenv import load_dotenv
from pymongo import MongoClient, TEXT
from pymongo.collection import Collection
from typing_extensions import Annotated, TypedDict
from langgraph.graph.message import add_messages
from datetime import datetime,timezone
from pydantic import BaseModel, Field
from langchain.chat_models import init_chat_model
from enum import Enum
from langgraph.types import Command
from typing import Literal, Optional
from langgraph.graph.state import StateGraph,START,END


load_dotenv()
os.environ["OPENROUTER_API_KEY"]=os.getenv("CUSTOM_API_KEY")
os.environ["GEMINI_API_KEY"]=os.getenv("GEMINI_API_KEY")



# from sales_agent import agent
# from buy_agent import buy_agent
# from payment_agent import payment_agent
# from support_agent import support_agent


llm = init_chat_model(model="openai/gpt-oss-120b:free", model_provider="openrouter")
print(llm)

def get_collection(db_name:str,col_name:str)->Collection:
    client = MongoClient(os.getenv("MONGO_URI"), serverSelectionTimeoutMS=5000)
    db=client[db_name]
    collection=db[col_name] #collections are different for different user. i will manage them in my mongodb
    return collection
    
class MemoryManager:
    def __init__(self, collection):
        self.collection = collection

    def update(self, user_id, **kwargs):
        kwargs["updated_at"] = datetime.now(timezone.utc)

        self.collection.update_one(
            {"user_id": user_id},
            {"$set": kwargs},
            upsert=True
        )

    def get(self, user_id):
        return self.collection.find_one({"user_id": user_id})  #should use **state["memory"] while i am willing to update only particular field

class Intent(str, Enum):
    BROWSE_PRODUCTS="get_products"
    FOLLOW_UP_QUESTIONS="follow_up"
    BUY_PRODUCT="buy_product"
    PAYMENT="payment"

class productQuery(BaseModel):
    product_type: str | None=None
    color: str | None=None
    max_price: float| None=None
    product_id: str | None=None
    intent: Intent | None = Field(
        default=None,
        description="""
        User intent classification:
        strictly classify them to one of the following intents. dont leave it none
        get_products: User wants product recommendations or product search or show <type>.
        follow_up: User is asking a question regarding previous product. either by mentioning it or without mentioning it
        buy_product: user wants to buy the product.
        payment: if user wants to pay. if they want to make the payment
        """
    )

short_term_memory=MemoryManager(get_collection("Spes-AI","short-term-memory"))
products=get_collection("Spes-AI","products")

class State(TypedDict, total=False):      # ← add total=False
    messages: Annotated[list, add_messages]
    price: Optional[float]
    user_id: Optional[str]
    variants: Optional[dict]
    approval_status: bool
    order_id: Optional[str]
    payment_url: Optional[str]