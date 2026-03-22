import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import ReactFlow, {
  Node,
  Edge,
  ReactFlowInstance,
  MarkerType,
  PanOnScrollMode,
  Background,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
} from 'reactflow';
import 'reactflow/dist/style.css';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { learningPathService } from '../services';
import type { LearningPath } from '../services';

interface PathState {
  path?: LearningPath;
}

interface LessonNode {
  lesson_id: string;
  title: string;
  chapter_index: number;
  lesson_index: number;
  status?: string;
  resources?: string[];
  summary?: string;
}

const getStatusLabel = (status?: string) => {
  switch (status) {
    case 'complete':
      return 'Hoàn thành';
    case 'in_progress':
      return 'Đang học';
    default:
      return 'Khóa';
  }
};

const LessonNodeComponent = ({
  data,
  selected,
}: {
  data: {
    lesson: LessonNode;
    onSelect: (lesson: LessonNode) => void;
  };
  selected: boolean;
}) => {
  const isComplete = data.lesson.status === 'complete';
  const isInProgress = data.lesson.status === 'in_progress';
  const isLocked = !isComplete && !isInProgress;

  return (
    <div
      onClick={() => data.onSelect(data.lesson)}
      className={`w-[320px] rounded-[32px] border-[3px] cursor-pointer transition-all text-center px-8 py-5 bg-[#d8c3d0] ${
        selected
          ? 'border-[#9f1537] shadow-[0_12px_32px_rgba(143,16,37,0.18)]'
          : 'border-[#cb6b88] shadow-[0_8px_20px_rgba(143,16,37,0.12)] hover:shadow-[0_10px_24px_rgba(143,16,37,0.16)]'
      }`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center justify-center gap-3 mb-2">
        {isComplete ? (
          <span className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-[#9f1537] text-white text-[22px] font-bold leading-none">
            ✓
          </span>
        ) : isInProgress ? (
          <span className="inline-flex items-center justify-center w-10 h-10 rounded-full bg-[#ce6a86] text-white text-[24px] font-bold leading-none">
            •
          </span>
        ) : (
          <span className="inline-flex items-center justify-center w-10 h-10 rounded-full border-2 border-[#ce6a86] text-[#8f1025] text-[18px] leading-none">
            🔒
          </span>
        )}
        <p className="font-semibold text-[#5b1724] text-[36px] leading-none tracking-[-0.02em]">
          Bài {data.lesson.chapter_index}.{data.lesson.lesson_index}
        </p>
      </div>
      <p
        className={`text-[38px] leading-none font-medium tracking-[-0.01em] ${
          isLocked ? 'text-[#6f2b3b]' : 'text-[#651628]'
        }`}
      >
        {isComplete ? 'Hoàn thành' : isInProgress ? 'Đang học' : getStatusLabel(data.lesson.status)}
      </p>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
};

const getLearningPathNotice = (path?: LearningPath | null) => {
  if (!path || path.curriculum_source !== 'fallback') {
    return null;
  }

  const reason = path.llm_status?.reason?.trim();
  if (reason) {
    return `${
      path.curriculum_notice ||
      'AI hiện chưa phản hồi ổn định. Hệ thống đã dùng lộ trình dự phòng để bạn vẫn có thể bắt đầu học.'
    } Lý do: ${reason}`;
  }

  return (
    path.curriculum_notice ||
    'AI hiện chưa phản hồi ổn định. Hệ thống đã dùng lộ trình dự phòng để bạn vẫn có thể bắt đầu học.'
  );
};

export default function LearningPathDetail() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { pathId } = useParams();
  const location = useLocation();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [path, setPath] = useState<LearningPath | null>(null);
  const [selectedLesson, setSelectedLesson] = useState<LessonNode | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance | null>(null);

  const statePath = (location.state as PathState | null)?.path;

  useEffect(() => {
    if (!user) {
      navigate('/login');
      return;
    }

    if (!pathId) {
      setError('Không tìm thấy lộ trình');
      setLoading(false);
      return;
    }

    if (statePath) {
      setPath(statePath);
      setLoading(false);
      return;
    }

    const loadPath = async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await learningPathService.getLearningPathById(pathId);
        if (response?.path_id) {
          setPath(response);
        } else {
          setError('Không tìm thấy lộ trình');
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Không thể tải lộ trình';
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    loadPath();
  }, [user, navigate, pathId, statePath]);

  const allLessons = useMemo(() => {
    const chapters = path?.chapters || path?.curriculum || [];
    const lessons: LessonNode[] = [];
    chapters.forEach((chapter: any, chapterIndex: number) => {
      chapter.lessons.forEach((lesson: any, lessonIndex: number) => {
        lessons.push({
          lesson_id: lesson.lesson_id,
          title: lesson.title,
          chapter_index: chapterIndex + 1,
          lesson_index: lessonIndex + 1,
          status: lesson.status,
          resources: lesson.resources,
          summary: lesson.summary,
        });
      });
    });
    return lessons;
  }, [path]);

  const curriculumNotice = useMemo(() => getLearningPathNotice(path), [path]);

  useEffect(() => {
    const flowNodes: Node[] = allLessons.map((lesson, index) => ({
      id: lesson.lesson_id,
      data: {
        lesson,
        onSelect: setSelectedLesson,
      },
      position: { x: 0, y: index * 136 },
      type: 'lesson',
    }));

    const flowEdges: Edge[] = allLessons
      .map((_, index) => {
        if (index < allLessons.length - 1) {
          return {
            id: `edge-${index}`,
            source: allLessons[index].lesson_id,
            target: allLessons[index + 1].lesson_id,
            type: 'smoothstep',
            animated: false,
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: '#ce6a86',
              width: 15,
              height: 15,
            },
            style: { stroke: '#c85d7c', strokeWidth: 2.4 },
          };
        }
        return null;
      })
      .filter(Boolean) as Edge[];

    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [allLessons, setNodes, setEdges]);

  useEffect(() => {
    if (allLessons.length === 0) {
      setSelectedLesson(null);
      return;
    }

    setSelectedLesson((previous) => {
      if (previous) {
        const updatedSelection = allLessons.find((lesson) => lesson.lesson_id === previous.lesson_id);
        if (updatedSelection) {
          return updatedSelection;
        }
      }

      return (
        allLessons.find((lesson) => lesson.status === 'in_progress') ||
        allLessons.find((lesson) => lesson.status === 'not_started') ||
        allLessons[0]
      );
    });
  }, [allLessons]);

  useEffect(() => {
    if (!flowInstance || !selectedLesson || nodes.length === 0) {
      return;
    }

    const selectedNode = nodes.find((node) => node.id === selectedLesson.lesson_id);
    if (!selectedNode) {
      return;
    }

    const nodeWidth = selectedNode.width ?? 210;
    const nodeHeight = selectedNode.height ?? 72;
    flowInstance.setCenter(
      selectedNode.position.x + nodeWidth / 2,
      selectedNode.position.y + nodeHeight / 2,
      {
        zoom: 1,
        duration: 420,
      }
    );
  }, [flowInstance, nodes, selectedLesson]);

  const handleBack = () => navigate('/learning-path');

  const handleViewResources = (lessonTitle: string) => {
    const query = encodeURIComponent(lessonTitle);
    navigate(`/resources?q=${query}`);
  };

  const handleLessonStatusUpdate = async (
    lessonId: string,
    status: 'not_started' | 'in_progress' | 'complete'
  ) => {
    if (!path?.path_id) {
      return;
    }

    try {
      const response = await learningPathService.updateLessonProgress({
        path_id: path.path_id,
        lesson_id: lessonId,
        status,
      });
      setError(null);

      setPath((prev: LearningPath | null) => {
        if (!prev?.curriculum) {
          return prev;
        }

        const updatedCurriculum = prev.curriculum.map((chapter: any) => ({
          ...chapter,
          lessons: chapter.lessons.map((lesson: any) => {
            if (lesson.lesson_id !== lessonId) {
              return lesson;
            }

            return {
              ...lesson,
              status: response.status,
            };
          }),
        }));

        return {
          ...prev,
          curriculum: updatedCurriculum,
        };
      });

      if (selectedLesson?.lesson_id === lessonId) {
        setSelectedLesson({
          ...selectedLesson,
          status: response.status,
        });
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể cập nhật tiến độ bài học';
      setError(message);
    }
  };

  return (
    <DashboardLayout>
      <div className="relative w-full h-full bg-[#fafafa] flex flex-col">
        <div className="flex items-center justify-between p-6 md:p-8 pb-4">
          <h1 className="text-[24px] md:text-[26px] leading-[1.2] font-bold text-[#901328] tracking-[-0.01em]">
            Lộ trình học tập - {path?.goal || 'Môn học'}
          </h1>
          <button
            onClick={handleBack}
            className="bg-white border border-[#8f1025] text-[#8f1025] text-[13px] font-medium px-4 py-2 rounded-[10px] hover:bg-gray-50 transition-colors"
          >
            Quay lại
          </button>
        </div>

        {loading ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-[#8f1025] mx-auto mb-3"></div>
              <p className="text-[#8f1025]">Đang tải lộ trình...</p>
            </div>
          </div>
        ) : error ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-[12px]">
              {error}
            </div>
          </div>
        ) : (
          <>
            {curriculumNotice && (
              <div className="px-8 mb-4">
                <div className="rounded-[16px] border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-900">
                  <div className="font-semibold">AI chưa sẵn sàng cho lần tạo lộ trình này</div>
                  <div className="mt-1">{curriculumNotice}</div>
                </div>
              </div>
            )}

            {allLessons.length > 0 ? (
              <div className="flex-1 flex flex-col xl:flex-row gap-4 px-4 md:px-8 pb-6 md:pb-8">
                <div className="flex-1 bg-white rounded-lg overflow-hidden border border-gray-200 min-h-[440px] md:min-h-[560px] xl:min-h-0">
                  <ReactFlow
                    nodes={nodes.map((node) => ({
                      ...node,
                      data: {
                        ...node.data,
                        lesson: {
                          ...node.data.lesson,
                          isSelected: selectedLesson?.lesson_id === node.data.lesson.lesson_id,
                        },
                      },
                    }))}
                    edges={edges}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    nodeTypes={{
                      lesson: (props: any) => (
                        <LessonNodeComponent
                          data={props.data}
                          selected={selectedLesson?.lesson_id === props.data.lesson.lesson_id}
                        />
                      ),
                    }}
                    nodesDraggable={false}
                    nodesConnectable={false}
                    elementsSelectable
                    zoomOnScroll={false}
                    zoomOnPinch={false}
                    panOnDrag={false}
                    panOnScroll
                    panOnScrollMode={PanOnScrollMode.Vertical}
                    fitView
                    fitViewOptions={{
                      padding: 0.22,
                    }}
                    minZoom={0.9}
                    maxZoom={1.25}
                    onInit={setFlowInstance}
                  >
                    <Background color="#e8d6de" gap={20} />
                  </ReactFlow>
                </div>

                {selectedLesson && (
                  <div className="w-full xl:w-[380px] xl:flex-shrink-0 bg-[#fefcfd] border-2 border-[#8f1025] rounded-[14px] p-5 md:p-6 flex flex-col min-h-[280px]">
                    <h3 className="text-[18px] leading-[1.3] font-semibold text-[#5b1724] mb-4">
                      Bài {selectedLesson.chapter_index}: {selectedLesson.title}
                    </h3>

                    <div className="border-t border-[#ddd] pt-4 pb-4 mb-4">
                      <p className="text-[12px] text-[#5b1724] font-medium">Mô tả</p>
                      <p className="text-[12px] text-[#666] mt-1">
                        {selectedLesson.summary || 'Không có mô tả'}
                      </p>
                    </div>

                    {selectedLesson.resources && selectedLesson.resources.length > 0 && (
                      <div className="space-y-2 mb-6">
                        {selectedLesson.resources.slice(0, 2).map((resource, idx) => (
                          <div key={idx} className="bg-[#f7dfed] rounded-[5px] px-3 py-2">
                            <p className="text-[12px] text-black">{resource}</p>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="flex gap-2 mt-auto">
                      {selectedLesson.status !== 'complete' && (
                        <button
                          onClick={() => handleLessonStatusUpdate(selectedLesson.lesson_id, 'in_progress')}
                          className="flex-1 px-3 py-2 text-[12px] font-medium border border-[#8f1025] text-[#8f1025] rounded-[8px] hover:bg-[#f7dfed] transition-colors"
                        >
                          Bắt đầu
                        </button>
                      )}
                      {selectedLesson.status !== 'complete' && (
                        <button
                          onClick={() => handleLessonStatusUpdate(selectedLesson.lesson_id, 'complete')}
                          className="flex-1 px-3 py-2 text-[12px] font-medium bg-[#8f1025] text-white rounded-[8px] hover:bg-[#7a0e20] transition-colors"
                        >
                          Hoàn thành
                        </button>
                      )}
                      <button
                        onClick={() => handleViewResources(selectedLesson.title)}
                        className="flex-1 px-3 py-2 text-[12px] font-medium border border-[#ce6a86] text-[#8f1025] rounded-[8px] hover:bg-[#f7dfed] transition-colors"
                      >
                        Tài nguyên
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center">
                <div className="bg-yellow-50 border border-yellow-200 text-yellow-700 px-4 py-3 rounded-[12px]">
                  Lộ trình chưa có bài học nào. Hãy thử tạo lại lộ trình với mục tiêu khác.
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </DashboardLayout>
  );
}
