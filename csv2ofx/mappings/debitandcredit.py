from operator import itemgetter

mapping = {
    "is_split": False,
    "has_header": True,
    "account": itemgetter("Account"),
    "date": itemgetter("Date"),
    "amount": itemgetter("Amount"),
    "payee": itemgetter("Payee"),
}