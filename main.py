import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, At

@register("astrbot_plugin_emma_merger", "Emma486-0", "多模态防抖合并插件", "1.0.0")
class EmmaMergerPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.message_bursts = {}
        self.pending_tasks = {}
        
        # 从配置文件读取，如果没有则用默认值
        self.debounce_time = self.config.get("debounce_time", 1.5)
        self.max_messages = self.config.get("max_messages", 10)

    def _get_burst_key(self, event: AstrMessageEvent) -> str:
        sender_id = event.get_sender_id()
        group_id = event.get_group_id() or "private"
        return f"{event.get_platform_id()}_{group_id}_{sender_id}"

    @filter.regex(r"^[\s\S]*$", priority=10000)
    async def early_catch(self, event: AstrMessageEvent):
        if event.message_str.startswith(("/", "!")):
            return

        burst_key = self._get_burst_key(event)
        if burst_key not in self.message_bursts:
            self.message_bursts[burst_key] = []
        
        # 防刷屏限制
        if len(self.message_bursts[burst_key]) < self.max_messages:
            self.message_bursts[burst_key].append(event.message_obj.message)
        else:
            print(f"[Emma Merger] 用户 {burst_key} 发送过快，已达到最大条数 {self.max_messages}，忽略当前消息。")

    @filter.on_waiting_llm_request(priority=1000)
    async def on_waiting_llm(self, event: AstrMessageEvent):
        burst_key = self._get_burst_key(event)
        current_task = asyncio.current_task()
        
        old_task = self.pending_tasks.get(burst_key)
        if old_task and old_task != current_task and not old_task.done():
            old_task.cancel()

        self.pending_tasks[burst_key] = current_task
        
        try:
            await asyncio.sleep(self.debounce_time)
        except asyncio.CancelledError:
            event.stop_event() 
            return
            
        if self.pending_tasks.get(burst_key) != current_task:
            event.stop_event()
            return

        if burst_key not in self.message_bursts:
            return
            
        chains = self.message_bursts[burst_key]
        if len(chains) == 0:
            return

        merged_chain = []
        current_text = ""
        
        for chain in chains:
            for comp in chain:
                if isinstance(comp, At) and str(getattr(comp, "qq", "")) == str(event.get_self_id()):
                    continue
                if isinstance(comp, Plain):
                    current_text += comp.text
                else:
                    if current_text:
                        merged_chain.append(Plain(current_text))
                        current_text = ""
                    merged_chain.append(comp)
        
        if current_text:
            merged_chain.append(Plain(current_text))

        merged_text = "".join([c.text for c in merged_chain if isinstance(c, Plain)])

        event.message_obj.message = merged_chain
        event.message_obj.message_str = merged_text
        event.message_str = merged_text
        
        print(f"[Emma Merger] 合并完成！包含 {len(chains)} 条消息。")

        del self.message_bursts[burst_key]
        if burst_key in self.pending_tasks:
            del self.pending_tasks[burst_key]