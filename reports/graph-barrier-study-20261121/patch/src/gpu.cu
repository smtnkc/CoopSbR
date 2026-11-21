#include "coopsbr/solver.hpp"
#include <cooperative_groups.h>
#include <cuda_runtime.h>
#include <algorithm>
#include <chrono>
#include <stdexcept>
#include <set>
#include <numeric>
#include <memory>
namespace coopsbr {
namespace cg=cooperative_groups;
constexpr int chunk_size=256;
struct State {
    Summary root, previous;
    Reversal candidate, chosen, fallback;
    int count=0, error=0, done=0, needs_candidate=0, initial_bp=0;
    int chunk_begin=0,chunk_end=0,expected_decreasing=0;
    unsigned long long phase_ns[6]{};
    unsigned long long barriers=0,updated=0,candidates=0,summarized=0,copies=0;
};
struct DeviceOptions { int size,chunks,incremental,candidate_mode,debug; int scalar=0; };
static void ck(cudaError_t e,const char* op) {
    if(e!=cudaSuccess) throw std::runtime_error(std::string(op)+": "+cudaGetErrorString(e));
}
template<class T> struct Buffer {
    T* p=nullptr;
    explicit Buffer(std::size_t n) { ck(cudaMalloc(&p,n*sizeof(T)),"cudaMalloc"); }
    ~Buffer() { if(p) cudaFree(p); }
    Buffer(const Buffer&)=delete; Buffer& operator=(const Buffer&)=delete;
};
__device__ static void store_summary(int* b,Summary s) {
    b[0]=s.minimum; b[1]=s.maximum; b[2]=s.decreasing;
    b[3]=s.breakpoints; b[4]=s.first; b[5]=s.second;
}
__device__ static Summary load_summary(const int* b) {
    Summary s; s.minimum=b[0];s.maximum=b[1];s.decreasing=b[2];
    s.breakpoints=b[3];s.first=b[4];s.second=b[5];return s;
}
__device__ static Summary block_reduce(Summary s) {
    __shared__ int scratch[256*6];
    int t=threadIdx.x;
    store_summary(scratch+6*t,s);
    __syncthreads();
    for(int offset=blockDim.x/2;offset;offset/=2) {
        if(t<offset) store_summary(scratch+6*t,combine(load_summary(scratch+6*t),load_summary(scratch+6*(t+offset))));
        __syncthreads();
    }
    s=load_summary(scratch);
    __syncthreads();
    return s;
}
// Every block has complete warps (32/64/128/256 threads). All threads
// participate, including those with zero input. Only thread 0 needs the result.
__device__ static int scalar_block_sum(int value) {
    __shared__ int warp_totals[8];
    int lane=threadIdx.x%32, warp=threadIdx.x/32;
    int subtotal=__reduce_add_sync(0xffffffffu,value);
    if(lane==0) warp_totals[warp]=subtotal;
    __syncthreads();
    int total=0;
    if(warp==0) {
        int own=lane<blockDim.x/32 ? warp_totals[lane] : 0;
        total=__reduce_add_sync(0xffffffffu,own);
    }
    // Protect the shared array if the helper is used again by this block.
    __syncthreads();
    return total;
}
__device__ static void positions(int* p,int* pos,State* state,DeviceOptions o) {
    int rank=blockIdx.x*blockDim.x+threadIdx.x, stride=gridDim.x*blockDim.x;
    if(rank==0) *state=State{};
    for(int i=rank;i<o.size;i+=stride) pos[p[i]]=i;
}
__device__ static void chunks_update(const int* p,Summary* chunks,State* s,DeviceOptions o,bool initial) {
    if(!initial && (s->done || s->error)) return;
    int lo=0,hi=o.chunks-1;
    if(!initial && o.incremental) {
        lo=(s->chosen.left-1)/chunk_size;
        hi=(s->chosen.right+1)/chunk_size;
    }
    for(int c=lo+blockIdx.x;c<=hi;c+=gridDim.x) {
        Summary own;
        for(int i=c*chunk_size+threadIdx.x;i<imin(o.size,(c+1)*chunk_size);i+=blockDim.x)
            own=combine(own,leaf(p,o.size,i));
        Summary total=block_reduce(own);
        if(threadIdx.x==0) chunks[c]=total;
    }
}
__device__ static void prepare(const int* p,const int* pos,const Summary* chunks,State* s,DeviceOptions o) {
    if(blockIdx.x!=0) return;
    Summary own;
    for(int c=threadIdx.x;c<o.chunks;c+=blockDim.x) own=combine(own,chunks[c]);
    Summary total=block_reduce(own);
    if(threadIdx.x!=0) return;
    s->root=total;
    if(s->count==0) { s->initial_bp=total.breakpoints; s->summarized=o.size; }
    if(o.debug) {
        Summary direct;
        for(int i=0;i<o.size;++i) {
            direct=combine(direct,leaf(p,o.size,i));
            if(pos[p[i]]!=i) s->error=1;
        }
        if(!equal(direct,total)) s->error=2;
        if(s->count>0) {
            Summary old=s->previous;
            bool good=old.decreasing ? total.breakpoints<old.breakpoints :
                      total.breakpoints==old.breakpoints && total.decreasing>0;
            if(old.decreasing && total.decreasing==0 && total.breakpoints>0)
                good=good && total.breakpoints<=old.breakpoints-2;
            if(!good) s->error=3;
        }
    }
    s->done=total.breakpoints==0 || s->error;
    if(s->done) return;
    s->previous=total;
    s->needs_candidate=total.decreasing!=0;
    if(s->needs_candidate) {
        s->candidate=minimum_reversal(total,pos);
        s->chunk_begin=o.candidate_mode==0 ? (s->candidate.left-1)/chunk_size : 0;
        s->chunk_end=o.candidate_mode==0 ? (s->candidate.right+1)/chunk_size : o.chunks-1;
        s->candidates+=imin(o.size,(s->chunk_end+1)*chunk_size)-s->chunk_begin*chunk_size;
        if(o.candidate_mode==2) s->copies+=o.size;
    } else s->chosen={total.first,total.second-1};
}
__device__ static void materialize(const int* p,int* temp,State* s,DeviceOptions o) {
    if(s->done || s->error || !s->needs_candidate || o.candidate_mode!=2) return;
    for(int i=blockIdx.x*blockDim.x+threadIdx.x;i<o.size;i+=gridDim.x*blockDim.x)
        temp[i]=viewed(p,i,s->candidate);
}
__device__ static void evaluate(const int* p,const int* temp,const Summary* chunks,int* partial,State* s,DeviceOptions o) {
    if(s->done || s->error || !s->needs_candidate) return;
    int delta=0;
    for(int c=s->chunk_begin+blockIdx.x;c<=s->chunk_end;c+=gridDim.x) {
        for(int i=c*chunk_size+threadIdx.x;i<imin(o.size,(c+1)*chunk_size);i+=blockDim.x)
            delta+=o.candidate_mode==2 ? decreasing_at(temp,o.size,i) : decreasing_at(p,o.size,i,s->candidate);
        if(threadIdx.x==0) delta-=chunks[c].decreasing;
    }
    int result;
    if(o.scalar) result=scalar_block_sum(delta);
    else {
        Summary own;own.decreasing=delta;
        result=block_reduce(own).decreasing;
    }
    if(threadIdx.x==0) partial[blockIdx.x]=result;
}
__device__ static void record_choice(Reversal* trace,State* s,DeviceOptions o,Reversal chosen) {
    trace[s->count++]={chosen.left-1,chosen.right-1};
    s->updated+=chosen.right-chosen.left+1;
    int lo=o.incremental ? (chosen.left-1)/chunk_size : 0;
    int hi=o.incremental ? (chosen.right+1)/chunk_size : o.chunks-1;
    s->summarized+=imin(o.size,(hi+1)*chunk_size)-lo*chunk_size;
}
__device__ static void choose(const int* p,const int* pos,const int* partial,Reversal* trace,State* s,DeviceOptions o,int blocks) {
    if(blockIdx.x!=0 || threadIdx.x!=0 || s->done || s->error) return;
    if(s->needs_candidate) {
        int count=s->root.decreasing;
        for(int b=0;b<blocks;++b) count+=partial[b];
        if(o.debug) {
            int expected=0;
            for(int i=1;i<o.size-1;++i) expected+=decreasing_at(p,o.size,i,s->candidate);
            if(count!=expected) { s->error=4;return; }
        }
        s->chosen=count>0 ? s->candidate : maximum_reversal(s->root,pos);
    }
    if(!valid(s->chosen,o.size) || s->count>=o.size-1) { s->error=5;return; }
    record_choice(trace,s,o,s->chosen);
}

// Consume only data published before evaluation completes. The live permutation
// and inverse positions may already be changing in another block.
__device__ static int replicated_candidate_count(const int* partial,int old_count) {
    int sum=0;
    for(int b=threadIdx.x;b<gridDim.x;b+=blockDim.x) sum+=partial[b];
    int total=scalar_block_sum(sum);
    __shared__ int block_count;
    if(threadIdx.x==0) block_count=old_count+total;
    __syncthreads();
    return block_count;
}
__device__ static void reverse_interval(int* p,int* pos,Reversal reversal) {
    int l=reversal.left,r=reversal.right;
    for(int k=blockIdx.x*blockDim.x+threadIdx.x;k<(r-l+1)/2;k+=gridDim.x*blockDim.x) {
        int a=p[l+k],b=p[r-k];
        p[l+k]=b;p[r-k]=a;pos[a]=r-k;pos[b]=l+k;
    }
}
enum class FusedCopy { none, full, changed, split_full };
enum class PublishedChoice { legacy, serial, parallel };

__device__ static bool contains(Reversal interval,int i) {
    return i>=interval.left && i<=interval.right;
}

template<FusedCopy Copy, bool Write=true, bool Summarize=true>
__device__ static void reverse_and_summarize(const int* old,int* next,int* pos,Summary* chunks,
                                              DeviceOptions o,Reversal chosen,Reversal previous) {
    const int lo=o.incremental ? (chosen.left-1)/chunk_size : 0;
    const int hi=o.incremental ? (chosen.right+1)/chunk_size : o.chunks-1;
    for(int c=blockIdx.x;c<o.chunks;c+=gridDim.x) {
        const bool summarize=c>=lo && c<=hi;
        Summary own;
        for(int i=c*chunk_size+threadIdx.x;i<imin(o.size,(c+1)*chunk_size);i+=blockDim.x) {
            if constexpr(Write) {
                const bool moved=contains(chosen,i);
                if(Copy!=FusedCopy::changed || moved || contains(previous,i)) {
                    const int value=viewed(old,i,chosen);
                    next[i]=value;
                    if(moved) pos[value]=i;
                }
            }
            if constexpr(Summarize) {
                if(summarize) own=combine(own,virtual_leaf(old,o.size,i,chosen));
            }
        }
        if constexpr(Summarize) {
            if(summarize) {
                Summary total=block_reduce(own);
                if(threadIdx.x==0) chunks[c]=total;
            }
        }
    }
}
__device__ static void reverse_values(int* p,int* pos,State* s) {
    if(!s->done && !s->error) reverse_interval(p,pos,s->chosen);
}
__device__ static void barrier(cg::grid_group grid,State* s) {
    if(grid.thread_rank()==0) ++s->barriers;
    grid.sync();
}
__device__ static unsigned long long timer_ns() {
    unsigned long long value;
    asm volatile("mov.u64 %0, %%globaltimer;" : "=l"(value) :: "memory");
    return value;
}
template<bool Profile> __device__ static void phase_stamp(State* s,unsigned long long& stamp,int index) {
    if constexpr(Profile) {
        if(blockIdx.x==0 && threadIdx.x==0) {
            auto now=timer_ns();s->phase_ns[index]+=now-stamp;stamp=now;
        }
    }
}
template<bool Profile,bool ReplicateChoice=false,FusedCopy Copy=FusedCopy::none,
         PublishedChoice Published=PublishedChoice::legacy>
__global__ void cooperative_sort(int* p,int* pos,Summary* chunks,int* partial,int* temp,Reversal* trace,
                                 State* s,DeviceOptions o,int* next) {
    auto grid=cg::this_grid();
    unsigned long long stamp=0;
    if constexpr(Profile) { if(grid.thread_rank()==0) stamp=timer_ns(); }
    positions(p,pos,s,o);
    Reversal previous;
    if constexpr(Copy==FusedCopy::changed) {
        for(int i=grid.thread_rank();i<o.size;i+=grid.size()) next[i]=p[i];
    }
    chunks_update(p,chunks,s,o,true);
    barrier(grid,s);
    phase_stamp<Profile>(s,stamp,0);
    for(int step=0;;++step) {
        prepare(p,pos,chunks,s,o);
        if constexpr(ReplicateChoice || Published!=PublishedChoice::legacy) {
            if(grid.thread_rank()==0 && !s->done && s->needs_candidate) {
                s->fallback=maximum_reversal(s->root,pos);
                if(o.debug) {
                    int count=0;
                    for(int i=1;i<o.size-1;++i)
                        count+=decreasing_at(p,o.size,i,s->candidate);
                    s->expected_decreasing=count;
                }
            }
        }
        barrier(grid,s);
        phase_stamp<Profile>(s,stamp,1);
        if(s->done || s->error) break;
        if(o.candidate_mode==2 && s->needs_candidate) {
            materialize(p,temp,s,o);barrier(grid,s);
        }
        evaluate(p,temp,chunks,partial,s,o);
        barrier(grid,s);
        phase_stamp<Profile>(s,stamp,2);
        if constexpr(ReplicateChoice) {
            const bool needs_candidate=s->needs_candidate;
            int count=needs_candidate ? replicated_candidate_count(partial,s->root.decreasing) : 0;
            Reversal chosen=needs_candidate ? (count>0 ? s->candidate : s->fallback) : s->chosen;
            const bool wrong_count=o.debug && needs_candidate && count!=s->expected_decreasing;
            const bool invalid_choice=!valid(chosen,o.size) || step>=o.size-1;
            if(grid.thread_rank()==0) {
                if(wrong_count || invalid_choice) s->error=wrong_count ? 4 : 5;
                else {
                    // No block reads the shared choice on the candidate path
                    // until the post-reversal barrier. On the strip path the
                    // choice was already published by prepare.
                    if(needs_candidate) s->chosen=chosen;
                    record_choice(trace,s,o,chosen);
                }
            }
            phase_stamp<Profile>(s,stamp,3);
            if(wrong_count || invalid_choice) break;
            if constexpr(Copy!=FusedCopy::none) {
                if constexpr(Copy==FusedCopy::split_full) {
                    reverse_and_summarize<Copy,true,false>(p,next,pos,chunks,o,chosen,previous);
                    barrier(grid,s);
                    reverse_and_summarize<Copy,false,true>(p,next,pos,chunks,o,chosen,previous);
                } else {
                    reverse_and_summarize<Copy>(p,next,pos,chunks,o,chosen,previous);
                }
                barrier(grid,s);
                phase_stamp<Profile>(s,stamp,4);
                int* old=p;
                p=next;
                next=old;
                previous=chosen;
                continue;
            }
            reverse_interval(p,pos,chosen);
        } else {
            if constexpr(Published==PublishedChoice::legacy) {
                choose(p,pos,partial,trace,s,o,gridDim.x);
            } else if(blockIdx.x==0) {
                int count=s->root.decreasing;
                if(s->needs_candidate) {
                    if constexpr(Published==PublishedChoice::parallel) {
                        count=replicated_candidate_count(partial,count);
                    } else if(threadIdx.x==0) {
                        for(int b=0;b<gridDim.x;++b) count+=partial[b];
                    }
                }
                if(threadIdx.x==0) {
                    const Reversal chosen=s->needs_candidate ? (count>0 ? s->candidate : s->fallback) : s->chosen;
                    if(!valid(chosen,o.size) || step>=o.size-1) s->error=5;
                    else if(o.debug && s->needs_candidate && count!=s->expected_decreasing) s->error=4;
                    else {
                        s->chosen=chosen;
                        record_choice(trace,s,o,chosen);
                    }
                }
            }
            barrier(grid,s);
            phase_stamp<Profile>(s,stamp,3);
            if(s->error) break;
            reverse_values(p,pos,s);
        }
        barrier(grid,s);
        phase_stamp<Profile>(s,stamp,4);
        chunks_update(p,chunks,s,o,false);
        barrier(grid,s);
        phase_stamp<Profile>(s,stamp,5);
    }
}
__global__ void initialize_kernel(int* p,int* pos,State* s,DeviceOptions o) { positions(p,pos,s,o); }
__global__ void chunks_kernel(const int* p,Summary* chunks,State* s,DeviceOptions o,bool initial) { chunks_update(p,chunks,s,o,initial); }
__global__ void prepare_kernel(const int* p,const int* pos,const Summary* chunks,State* s,DeviceOptions o) { prepare(p,pos,chunks,s,o); }
__global__ void materialize_kernel(const int* p,int* temp,State* s,DeviceOptions o) { materialize(p,temp,s,o); }
__global__ void evaluate_kernel(const int* p,const int* temp,const Summary* chunks,int* partial,State* s,DeviceOptions o) { evaluate(p,temp,chunks,partial,s,o); }
__global__ void choose_kernel(const int* p,const int* pos,const int* partial,Reversal* trace,State* s,DeviceOptions o,int blocks) { choose(p,pos,partial,trace,s,o,blocks); }
__global__ void reverse_kernel(int* p,int* pos,State* s) { reverse_values(p,pos,s); }
// The graph edges provide global ordering between existing stage kernels.
// prepare owns the decision/termination predicate; no state returns to the CPU
// between reversals. Identity inputs therefore skip the body entirely.
__global__ void graph_prepare_kernel(const int* p,const int* pos,const Summary* chunks,
                                     State* s,DeviceOptions o,cudaGraphConditionalHandle handle) {
    prepare(p,pos,chunks,s,o);
    if(threadIdx.x==0) cudaGraphSetConditional(handle,(!s->done && !s->error) ? 1u : 0u);
}
struct ExecutionGraph {
    cudaGraph_t graph=nullptr;
    cudaGraphExec_t executable=nullptr;
    explicit ExecutionGraph() { ck(cudaGraphCreate(&graph,0),"graph create"); }
    ~ExecutionGraph() {
        if(executable) cudaGraphExecDestroy(executable);
        if(graph) cudaGraphDestroy(graph);
    }
    ExecutionGraph(const ExecutionGraph&)=delete;
    ExecutionGraph& operator=(const ExecutionGraph&)=delete;
    static cudaGraphNode_t add(cudaGraph_t owner,cudaGraphNode_t dependency,void* function,
                               int blocks,int threads,void** args) {
        cudaKernelNodeParams params{};
        params.func=function;params.gridDim=dim3(blocks);params.blockDim=dim3(threads);
        params.kernelParams=args;
        cudaGraphNode_t node=nullptr;
        ck(cudaGraphAddKernelNode(&node,owner,dependency?&dependency:nullptr,dependency?1:0,&params),"graph kernel node");
        return node;
    }
    void build(int* p,int* pos,Summary* chunks,int* partial,int* temp,Reversal* trace,
               State* state,DeviceOptions o,int blocks,int threads) {
        cudaGraphConditionalHandle handle;
        ck(cudaGraphConditionalHandleCreate(&handle,graph,0,cudaGraphCondAssignDefault),"graph conditional handle");
        void* init[]={&p,&pos,&state,&o};
        auto last=add(graph,nullptr,reinterpret_cast<void*>(initialize_kernel),blocks,threads,init);
        bool initial=true;
        void* summarize[]={&p,&chunks,&state,&o,&initial};
        last=add(graph,last,reinterpret_cast<void*>(chunks_kernel),blocks,threads,summarize);
        void* prepare_args[]={&p,&pos,&chunks,&state,&o,&handle};
        last=add(graph,last,reinterpret_cast<void*>(graph_prepare_kernel),1,threads,prepare_args);
        cudaGraphNodeParams conditional{};
        conditional.type=cudaGraphNodeTypeConditional;
        conditional.conditional.handle=handle;
        conditional.conditional.type=cudaGraphCondTypeWhile;
        conditional.conditional.size=1;
        cudaGraphNode_t loop=nullptr;
        ck(cudaGraphAddNode(&loop,graph,&last,1,&conditional),"graph WHILE node");
        cudaGraph_t body=conditional.conditional.phGraph_out[0];
        last=nullptr;
        if(o.candidate_mode==2) {
            void* copy_args[]={&p,&temp,&state,&o};
            last=add(body,last,reinterpret_cast<void*>(materialize_kernel),blocks,threads,copy_args);
        }
        void* evaluate_args[]={&p,&temp,&chunks,&partial,&state,&o};
        last=add(body,last,reinterpret_cast<void*>(evaluate_kernel),blocks,threads,evaluate_args);
        void* choose_args[]={&p,&pos,&partial,&trace,&state,&o,&blocks};
        last=add(body,last,reinterpret_cast<void*>(choose_kernel),1,threads,choose_args);
        void* reverse_args[]={&p,&pos,&state};
        last=add(body,last,reinterpret_cast<void*>(reverse_kernel),blocks,threads,reverse_args);
        initial=false;
        last=add(body,last,reinterpret_cast<void*>(chunks_kernel),blocks,threads,summarize);
        add(body,last,reinterpret_cast<void*>(graph_prepare_kernel),1,threads,prepare_args);
        ck(cudaGraphInstantiate(&executable,graph,nullptr,nullptr,0),"graph instantiate");
        ck(cudaGraphUpload(executable,0),"graph upload");
        ck(cudaStreamSynchronize(0),"graph upload completion");
    }
};
struct Event {
    cudaEvent_t value=nullptr;
    explicit Event(bool active=true) { if(active) ck(cudaEventCreate(&value),"event create"); }
    ~Event() { if(value) cudaEventDestroy(value); }
};
namespace {
using Clock=std::chrono::steady_clock;
using CoopKernel=decltype(&cooperative_sort<false>);
static double elapsed(Clock::time_point a,Clock::time_point b) {
    return std::chrono::duration<double,std::milli>(b-a).count();
}
template<bool Profile>
CoopKernel pick_kernel(const std::string& mode) {
    if(mode=="cooperative-matched-serial") return cooperative_sort<Profile,false,FusedCopy::none,PublishedChoice::serial>;
    if(mode=="cooperative-matched-parallel") return cooperative_sort<Profile,false,FusedCopy::none,PublishedChoice::parallel>;
    if(mode=="cooperative-replicated") return cooperative_sort<Profile,true>;
    if(mode=="cooperative-split-full") return cooperative_sort<Profile,true,FusedCopy::split_full>;
    if(mode=="cooperative-fused-full") return cooperative_sort<Profile,true,FusedCopy::full>;
    if(mode=="cooperative-fused-changed") return cooperative_sort<Profile,true,FusedCopy::changed>;
    return cooperative_sort<Profile>;
}
struct GpuConfiguration {
    Options options;
    CoopKernel kernel;
    DeviceOptions device;
    int n,blocks,threads;
    bool fused,cooperative,graph_mode;
    double context_ms;
};
GpuConfiguration configure_gpu(int n,const Options& options) {
    auto start=Clock::now();
    ck(cudaFree(nullptr),"context initialization");
    int device_id=0;
    ck(cudaGetDevice(&device_id),"cudaGetDevice");
    cudaDeviceProp prop{};
    ck(cudaGetDeviceProperties(&prop,device_id),"properties");
    if(prop.major!=8 || prop.minor!=9) throw std::runtime_error("This native sm_89 build requires an Ada GPU");
    const int threads=options.threads;
    if(threads!=32 && threads!=64 && threads!=128 && threads!=256)
        throw std::runtime_error("Threads must be 32, 64, 128, or 256");
    auto capacity_for=[&](CoopKernel kernel) {
        int active=0;
        ck(cudaOccupancyMaxActiveBlocksPerMultiprocessor(&active,kernel,threads,0),"occupancy");
        return active*prop.multiProcessorCount;
    };
    auto kernel=options.instrument ? pick_kernel<true>(options.coordination) : pick_kernel<false>(options.coordination);
    int capacity=capacity_for(kernel);
    if(options.matched_grid) {
        for(const char* mode : {"cooperative", "cooperative-matched-serial", "cooperative-matched-parallel",
                                "cooperative-replicated", "cooperative-split-full", "cooperative-fused-full",
                                "cooperative-fused-changed"}) {
            capacity=std::min(capacity,capacity_for(pick_kernel<false>(mode)));
        }
    }
    const int size=n+2,chunk_count=(size+chunk_size-1)/chunk_size;
    const int blocks=options.blocks ? options.blocks : std::min(chunk_count,capacity);
    if(blocks<1 || blocks>capacity) throw std::runtime_error("Grid exceeds actual cooperative kernel residency");
    const bool cooperative=options.coordination.compare(0,11,"cooperative")==0;
    const bool graph_mode=options.coordination=="graph";
    const bool fused=options.coordination=="cooperative-split-full" ||
        options.coordination=="cooperative-fused-full" || options.coordination=="cooperative-fused-changed";
    if(graph_mode && options.instrument) throw std::runtime_error("Graph phase instrumentation is not supported");
    if(cooperative && !prop.cooperativeLaunch) throw std::runtime_error("Cooperative launch is not supported");
    DeviceOptions o{size,chunk_count,options.update=="incremental",options.candidate=="local"?0:options.candidate=="full"?1:2,
                    options.debug,options.reduction=="scalar"};
    return {options,kernel,o,n,blocks,threads,fused,cooperative,graph_mode,elapsed(start,Clock::now())};
}
struct DeviceWorkspace {
    Buffer<int> p,pos,partial,temp;
    Buffer<Summary> chunks;
    Buffer<Reversal> trace;
    Buffer<State> state;
    std::unique_ptr<Buffer<int>> alternate;
    std::unique_ptr<ExecutionGraph> graph;
    explicit DeviceWorkspace(const GpuConfiguration& config)
        :p(config.device.size),pos(config.device.size),partial(config.blocks),
         temp(config.device.candidate_mode==2 ? config.device.size : 1),chunks(config.device.chunks),
         trace(config.n+1),state(1) {
        if(config.fused) alternate=std::make_unique<Buffer<int>>(config.device.size);
    }
    std::unique_ptr<ExecutionGraph> make_graph(const GpuConfiguration& config) {
        auto executable=std::make_unique<ExecutionGraph>();
        executable->build(p.p,pos.p,chunks.p,partial.p,temp.p,trace.p,state.p,config.device,config.blocks,config.threads);
        return executable;
    }
};
Result run_gpu(const std::vector<int>& input,const GpuConfiguration& config,DeviceWorkspace* reusable) {
    auto begin=Clock::now();
    DeviceOptions o=config.device;
    const auto& options=config.options;
    const auto kernel=config.kernel;
    const int n=config.n,size=o.size,chunk_count=o.chunks,blocks=config.blocks,threads=config.threads;
    const bool fused=config.fused,cooperative=config.cooperative,graph_mode=config.graph_mode;
    std::vector<int> padded(size);padded[0]=0;padded[size-1]=size-1;
    std::copy(input.begin(),input.end(),padded.begin()+1);
    Result result;result.context_ms=reusable ? 0 : config.context_ms;result.blocks=blocks;result.threads=threads;
    result.sorted.resize(n);result.trace.resize(n+1);
    std::unique_ptr<DeviceWorkspace> temporary;
    if(!reusable) temporary=std::make_unique<DeviceWorkspace>(config);
    auto& workspace=reusable ? *reusable : *temporary;
    auto& p=workspace.p;auto& pos=workspace.pos;auto& partial=workspace.partial;
    auto& temp=workspace.temp;auto& chunks=workspace.chunks;auto& trace=workspace.trace;auto& state=workspace.state;
    int* next=workspace.alternate ? workspace.alternate->p : nullptr;
    result.allocated_bytes=(2ULL*size+blocks+(o.candidate_mode==2?size:1))*sizeof(int)+chunk_count*sizeof(Summary)
        +(n+1ULL)*sizeof(Reversal)+sizeof(State)+(fused?size*sizeof(int):0);
    State host;
    {
        Event phase_begin(options.instrument),phase_end(options.instrument);
        auto timed=[&](int index,auto launch) {
            if(!options.instrument) { launch();return; }
            ck(cudaEventRecord(phase_begin.value),"phase begin");launch();
            ck(cudaEventRecord(phase_end.value),"phase end");
            ck(cudaEventSynchronize(phase_end.value),"phase completion");
            float value=0;ck(cudaEventElapsedTime(&value,phase_begin.value,phase_end.value),"phase elapsed");
            result.phase_ms[index]+=value;
        };
        auto allocated=Clock::now();result.allocation_ms=elapsed(begin,allocated);
        std::unique_ptr<ExecutionGraph> call_graph;
        ExecutionGraph* graph=workspace.graph.get();
        if(graph_mode) {
            if(!graph) {
                auto setup_start=Clock::now();
                call_graph=workspace.make_graph(config);
                graph=call_graph.get();
                result.graph_setup_ms=elapsed(setup_start,Clock::now());
            }
            result.graph_nodes=9+(o.candidate_mode==2 ? 1 : 0);
        }
        auto transfer_start=Clock::now();
        ck(cudaMemcpy(p.p,padded.data(),size*sizeof(int),cudaMemcpyHostToDevice),"input transfer");
        auto start=Clock::now();result.h2d_ms=elapsed(transfer_start,start);
        if(graph_mode) {
            ck(cudaGraphLaunch(graph->executable,0),"graph launch");
            result.graph_launches=1;
        } else if(cooperative) {
            void* args[]={&p.p,&pos.p,&chunks.p,&partial.p,&temp.p,&trace.p,&state.p,&o,&next};
            ck(cudaLaunchCooperativeKernel(reinterpret_cast<void*>(kernel),dim3(blocks),dim3(threads),args),"cooperative launch");
            result.launches=1;
        } else {
            timed(0,[&]{
                initialize_kernel<<<blocks,threads>>>(p.p,pos.p,state.p,o);
                chunks_kernel<<<blocks,threads>>>(p.p,chunks.p,state.p,o,true);
            });result.launches=2;
            while(true) {
                timed(1,[&]{ prepare_kernel<<<1,threads>>>(p.p,pos.p,chunks.p,state.p,o); });++result.launches;
                ck(cudaGetLastError(),"prepare launch");
                ck(cudaMemcpy(&host,state.p,sizeof(State),cudaMemcpyDeviceToHost),"decision status");
                if(host.done || host.error) break;
                timed(2,[&]{
                    if(o.candidate_mode==2 && host.needs_candidate) {
                        materialize_kernel<<<blocks,threads>>>(p.p,temp.p,state.p,o);++result.launches;
                    }
                    evaluate_kernel<<<blocks,threads>>>(p.p,temp.p,chunks.p,partial.p,state.p,o);
                });
                timed(3,[&]{ choose_kernel<<<1,threads>>>(p.p,pos.p,partial.p,trace.p,state.p,o,blocks); });
                timed(4,[&]{ reverse_kernel<<<blocks,threads>>>(p.p,pos.p,state.p); });
                timed(5,[&]{ chunks_kernel<<<blocks,threads>>>(p.p,chunks.p,state.p,o,false); });result.launches+=4;
                ck(cudaGetLastError(),"sorting stage launch");
            }
        }
        ck(cudaGetLastError(),"sorting launch");ck(cudaDeviceSynchronize(),"sorting completion");
        auto end=Clock::now();result.sort_ms=elapsed(start,end);
        ck(cudaMemcpy(&host,state.p,sizeof(State),cudaMemcpyDeviceToHost),"final status");
        if(host.error || host.count<0 || host.count>n+1 || host.count>host.initial_bp)
            throw std::runtime_error("GPU policy/state invariant failed, code="+std::to_string(host.error));
        const int* final_values=fused && host.count%2 ? next : p.p;
        ck(cudaMemcpy(padded.data(),final_values,size*sizeof(int),cudaMemcpyDeviceToHost),"result transfer");
        ck(cudaMemcpy(result.trace.data(),trace.p,host.count*sizeof(Reversal),cudaMemcpyDeviceToHost),"trace transfer");
        result.d2h_ms=elapsed(end,Clock::now());
        result.trace.resize(host.count);std::copy(padded.begin()+1,padded.end()-1,result.sorted.begin());
        if(graph_mode) result.launches=3ULL+(5ULL+(o.candidate_mode==2?1ULL:0ULL))*host.count;
        result.initial_breakpoints=host.initial_bp;result.barriers=host.barriers;
        result.updated_elements=host.updated;result.candidate_elements=host.candidates;
        if(cooperative && options.instrument) for(int i=0;i<6;++i) result.phase_ms[i]=host.phase_ns[i]*1e-6;
        result.summary_elements=host.summarized;result.candidate_copy_elements=host.copies;
        if(call_graph) {
            auto teardown_start=Clock::now();
            call_graph.reset();
            result.graph_teardown_ms=elapsed(teardown_start,Clock::now());
        }
    }
    temporary.reset();
    result.end_to_end_ms=elapsed(begin,Clock::now());
    return result;
}
} // namespace

struct PreparedGpu::Impl {
    GpuConfiguration config;
    std::unique_ptr<DeviceWorkspace> workspace;
    double setup_time_ms;
    Impl(int n,const Options& options,bool reuse_graph):config(configure_gpu(n,options)) {
        if(reuse_graph && !config.graph_mode) throw std::runtime_error("Graph reuse requires Graph coordination");
        auto start=Clock::now();
        workspace=std::make_unique<DeviceWorkspace>(config);
        if(reuse_graph) workspace->graph=workspace->make_graph(config);
        setup_time_ms=elapsed(start,Clock::now());
    }
};
PreparedGpu::PreparedGpu(int n,const Options& options,bool reuse_graph)
    :impl_(std::make_unique<Impl>(n,options,reuse_graph)) {}
PreparedGpu::~PreparedGpu()=default;
double PreparedGpu::setup_ms() const { return impl_->setup_time_ms; }
Result PreparedGpu::solve(const std::vector<int>& input) {
    if(input.size()!=static_cast<std::size_t>(impl_->config.n)) throw std::runtime_error("Prepared solver input size changed");
    return run_gpu(input,impl_->config,impl_->workspace.get());
}
Result solve_gpu(const std::vector<int>& input,const Options& options) {
    const auto config=configure_gpu(static_cast<int>(input.size()),options);
    return run_gpu(input,config,nullptr);
}
__global__ void root_kernel(const Summary* chunks,Summary* root,DeviceOptions o) {
    Summary own;
    for(int c=threadIdx.x;c<o.chunks;c+=blockDim.x) own=combine(own,chunks[c]);
    auto total=block_reduce(own);
    if(threadIdx.x==0) *root=total;
}
std::vector<UpdateMeasurement> benchmark_updates(const std::vector<int>& input,
        const std::vector<Reversal>& trace,int max_states,int repetitions) {
    if(max_states<1 || max_states>64 || repetitions<1 || repetitions>10)
        throw std::runtime_error("Benchmark limits: 1..64 states, 1..10 repetitions");
    ck(cudaFree(nullptr),"benchmark context");
    std::vector<int> order(trace.size());std::iota(order.begin(),order.end(),0);
    std::stable_sort(order.begin(),order.end(),[&](int a,int b){
        return trace[a].right-trace[a].left<trace[b].right-trace[b].left;
    });
    std::set<int> selected;
    if(!trace.empty()) {
        int count=std::min(max_states,static_cast<int>(trace.size()));
        for(int i=0;i<count;++i) selected.insert(order[count==1?0:i*(order.size()-1)/(count-1)]);
    }
    int n=static_cast<int>(input.size()),size=n+2,num_chunks=(size+chunk_size-1)/chunk_size;
    int blocks=std::min(num_chunks,128),threads=128;
    std::vector<int> current(size),after(size),device_values(size),device_pos(size);
    current[0]=0;current.back()=size-1;std::copy(input.begin(),input.end(),current.begin()+1);
    Buffer<int> p(size),pos(size);Buffer<Summary> chunks(num_chunks),root(1);Buffer<State> state(1);
    Event start,middle,finish;
    std::vector<UpdateMeasurement> rows;
    for(int step=0;step<static_cast<int>(trace.size());++step) {
        Reversal r{trace[step].left+1,trace[step].right+1};
        if(!valid(r,size)) throw std::runtime_error("Invalid source trace");
        if(selected.count(step)) {
            after=current;std::reverse(after.begin()+r.left,after.begin()+r.right+1);
            Summary expected,before;
            for(int i=0;i<size;++i) {
                expected=combine(expected,leaf(after.data(),size,i));
                before=combine(before,leaf(current.data(),size,i));
            }
            for(int rep=-1;rep<repetitions;++rep) for(int order_index=0;order_index<2;++order_index) {
                int variant=(rep+1+order_index)%2;
                DeviceOptions o{size,num_chunks,variant,0,0};
                ck(cudaMemcpy(p.p,current.data(),size*sizeof(int),cudaMemcpyHostToDevice),"restore snapshot");
                initialize_kernel<<<blocks,threads>>>(p.p,pos.p,state.p,o);
                chunks_kernel<<<blocks,threads>>>(p.p,chunks.p,state.p,o,true);
                ck(cudaDeviceSynchronize(),"snapshot initialization");
                State h;h.chosen=r;
                ck(cudaMemcpy(state.p,&h,sizeof(State),cudaMemcpyHostToDevice),"prescribed reversal");
                auto begin=std::chrono::steady_clock::now();
                ck(cudaEventRecord(start.value),"start event");
                reverse_kernel<<<blocks,threads>>>(p.p,pos.p,state.p);
                ck(cudaEventRecord(middle.value),"middle event");
                chunks_kernel<<<blocks,threads>>>(p.p,chunks.p,state.p,o,false);
                root_kernel<<<1,threads>>>(chunks.p,root.p,o);
                ck(cudaEventRecord(finish.value),"finish event");
                ck(cudaEventSynchronize(finish.value),"update completion");
                double wall=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count();
                float reverse_ms=0,metadata_ms=0;
                ck(cudaEventElapsedTime(&reverse_ms,start.value,middle.value),"reverse interval");
                ck(cudaEventElapsedTime(&metadata_ms,middle.value,finish.value),"metadata interval");
                Summary actual;
                ck(cudaMemcpy(&actual,root.p,sizeof(Summary),cudaMemcpyDeviceToHost),"updated root");
                ck(cudaMemcpy(device_values.data(),p.p,size*sizeof(int),cudaMemcpyDeviceToHost),"updated values");
                ck(cudaMemcpy(device_pos.data(),pos.p,size*sizeof(int),cudaMemcpyDeviceToHost),"updated positions");
                if(!equal(actual,expected) || device_values!=after) throw std::runtime_error("Update benchmark state mismatch");
                for(int i=0;i<size;++i) if(device_pos[after[i]]!=i) throw std::runtime_error("Update benchmark position mismatch");
                if(rep>=0) {
                    int lo=variant?(r.left-1)/chunk_size:0,hi=variant?(r.right+1)/chunk_size:num_chunks-1;
                    rows.push_back({step,r.right-r.left+1,before.breakpoints+1,
                        imin(size,(hi+1)*chunk_size)-lo*chunk_size,rep,variant!=0,reverse_ms,metadata_ms,wall});
                }
            }
        }
        std::reverse(current.begin()+r.left,current.begin()+r.right+1);
    }
    for(int i=0;i<size;++i) if(current[i]!=i) throw std::runtime_error("Source trace does not sort input");
    return rows;
}

}
