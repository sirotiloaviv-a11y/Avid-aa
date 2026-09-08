import asyncio, json, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from parallel_buy_demo.mock_exchange import MockExchange, OrderRejected

SYM="BTC/USDT"; N=100; BUD=100_000.0; TOTAL=N*BUD

async def run_parallel():
    ex=MockExchange(); start=ex.best_ask; out=[]
    async def buy(i):
        try:
            o=await ex.create_market_buy_order(SYM,params={"quoteOrderQty":BUD,"_account":f"acct{i:03d}"})
            out.append(o)
        except OrderRejected: pass
    await asyncio.gather(*(buy(i) for i in range(N)))
    return ex,start,out

async def run_twap(slices=100,pause=0.0):
    ex=MockExchange(); start=ex.best_ask; out=[]
    for i in range(slices):
        out.append(await ex.create_market_buy_order(SYM,params={"quoteOrderQty":TOTAL/slices,"_account":"acct000"}))
        ex.replenish()
    return ex,start,out

def summarize(ex,start,orders):
    filled=sum(o.filled_base for o in orders); spent=sum(o.cost_quote for o in orders)
    return dict(n=len(orders),btc=filled,spent=spent,start=start,avg=spent/filled,
                final_ask=ex.best_ask,slip_pct=(spent/filled/start-1)*100,
                slip_usd=spent-filled*start)

async def main():
    exb,sb,ob=await run_parallel()
    exc,sc,oc=await run_twap()
    # arrival-order sequence (tape order = matching order)
    seqB=[{"i":k,"avg":o.average,"btc":o.filled_base,"top":max(f.price for f in o.fills),
           "acct":o.account} for k,o in enumerate(exb.tape)]
    seqC=[{"i":k,"avg":o.average,"btc":o.filled_base,"top":max(f.price for f in o.fills)}
          for k,o in enumerate(exc.tape)]
    # depth ladder of a fresh book: cumulative BTC vs price
    ref=MockExchange()
    ladder=[]
    cum=0.0
    for i in range(0,3000,20):
        cum=ref.level_size*(i+1)
        ladder.append({"price":ref.start_price+i*ref.tick,"cum":cum})
    data=dict(
      book=dict(best_ask=ref.best_ask, depth_01=ref.depth_within(0.1),
                depth_05=ref.depth_within(0.5), depth_1=ref.depth_within(1.0),
                tick=ref.tick, level=ref.level_size),
      target=TOTAL,
      parallel=summarize(exb,sb,ob), twap=summarize(exc,sc,oc),
      seq_parallel=seqB, seq_twap=seqC, ladder=ladder,
      rejected_a=dict(n=100, reason="amount 100,000 BTC exceeds max order size 9,000 BTC (MARKET_LOT_SIZE)"),
    )
    print(json.dumps(data))

asyncio.run(main())
